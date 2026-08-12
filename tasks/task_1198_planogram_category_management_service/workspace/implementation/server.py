"""
Planogram & Category Management Service — reference implementation.

Stack: Python + Flask, in-memory store, logical clock.
Spec: workspace/PRD.md + SCAFFOLD.yaml (task 1198).

Envelope (PRD §2.2):
  success: {"meta": {"api_request_id": "req_...", "api_request_timestamp": iso},
            "response_type": "object" | "array", "data": ...}
  error:   {"meta": {...}, "response_type": "error",
            "data": {"error_id": "...", "message": "..."}}
  list meta also carries limit / offset / total_count / has_more.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone, time as dtime
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from functools import wraps

from flask import Flask, jsonify, request

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROLES = {
    "PlatformAdmin",
    "RetailerAdmin",
    "CategoryManager",
    "CategoryCaptain",
    "FieldAuditor",
    "AuditReviewer",
    "ResetCoordinator",
}
ALL_ROLES = frozenset(ROLES)

CATEGORY_ROLES = {"DESTINATION", "ROUTINE", "CONVENIENCE", "SEASONAL"}
VARIANTS = {"BASE", "CLUSTER_A", "CLUSTER_B"}

CLOCK_START = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

DOS_UNDERSTOCK_DAYS = 3.0
DOS_OVERSTOCK_DAYS = 21.0
DOS_ZERO_SENTINEL = 9999.0
INDEXED_ZERO_SALES_SENTINEL = 999.0
DEFAULT_COMPLIANCE_THRESHOLD_PCT = 85
COMPLIANCE_WARN_BELOW = 10
FAIL_RESET_WINDOW_DAYS = 14
DEFAULT_MAX_CONCURRENT = 1

# Non-terminal statuses used by the category archive guard (PRD §3.1)
PLANOGRAM_OPEN_STATUSES = {"DRAFT", "IN_REVIEW", "APPROVED", "ACTIVE"}
PROJECT_OPEN_STATUSES = {"PROPOSED", "SCHEDULED", "IN_PROGRESS"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def e400(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def e401(msg="Missing or unrecognized X-User-ID / X-User-Role headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def e403(msg="Role is not permitted to invoke this endpoint"):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def e404(msg="Resource not found in retailer scope"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def e409(msg="Entity is not in a state that permits the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def e422(msg="Business rule violation"):
    return ApiError("ERR_VALIDATION", 422, msg)


# ---------------------------------------------------------------------------
# In-memory store + logical clock
# ---------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.clock = CLOCK_START
        self.seq = 0
        self.retailers = {}
        self.categories = {}
        self.suppliers = {}
        self.products = {}
        self.planograms = {}
        self.lines = {}
        self.stores = {}
        self.audits = {}
        self.deals = {}
        self.projects = {}
        self.crews = {}
        self.assignments = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()
LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def now():
    return db.clock


def fmt_ms(dt):
    """ISO 8601 UTC with three fractional digits (PRD §2.2/§2.4)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_dt(dt):
    """ISO 8601 UTC; seconds precision when there is no sub-second part."""
    if dt.microsecond:
        return fmt_ms(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value, field):
    if not isinstance(value, str):
        raise e400(f"Field '{field}' must be an ISO 8601 datetime string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        raise e400(f"Field '{field}' must be an ISO 8601 datetime string")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------

def meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": fmt_ms(now()),
    }


def success_object(data, status=200):
    body = {"meta": meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, total_count, limit, offset):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + limit) < total_count
    body = {"meta": m, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------

def new_entity(**fields):
    ts = fmt_ms(now())
    ent = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    ent.update(fields)
    return ent


def touch(ent):
    ent["updated_at"] = fmt_ms(now())
    ent["version"] += 1


def pub(ent):
    """Public serialization: strip internal (underscore-prefixed) fields."""
    return {k: v for k, v in ent.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Decimal math helpers (PRD §2.6 — half-up rounding, never float math)
# ---------------------------------------------------------------------------

def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return float(Decimal(value).quantize(q, rounding=ROUND_HALF_UP))


def compute_dos(product, capacity_units):
    """Days of supply, provisional variant: 2dp half-up; sentinel on zero demand."""
    weekly = product["weekly_demand_units"]
    if weekly == 0:
        return DOS_ZERO_SENTINEL
    daily = Decimal(weekly) / Decimal(7)
    dos = Decimal(capacity_units) / daily
    return round_half_up(dos, 2)


def dos_flag_for(dos):
    """Thresholds on the rounded dos; boundaries are inclusive of healthy."""
    if dos < DOS_UNDERSTOCK_DAYS:
        return "UNDERSTOCK"
    if dos > DOS_OVERSTOCK_DAYS:
        return "OVERSTOCK"
    return "OK"


def snap_down_half_day(dos):
    """Finalized variant: snap down to the greatest 0.5 boundary <= value."""
    if dos == DOS_ZERO_SENTINEL:
        return DOS_ZERO_SENTINEL
    d = Decimal(repr(dos))
    snapped = (d * 2).to_integral_value(rounding=ROUND_FLOOR) / 2
    return float(snapped)


def compute_labor(project, planogram):
    """labor_hours_estimated = total_facings*0.05 + product_changes*0.25 (1dp half-up).

    product_changes counts lines on the target planogram whose product is absent
    from the store's currently installed planogram — the ACTIVE planogram of the
    project's category for the store's cluster, excluding the target itself.
    """
    store = db.stores.get(project["store_id"])
    installed = None
    if store is not None:
        for other in db.planograms.values():
            if (
                other["category_id"] == project["category_id"]
                and other["status"] == "ACTIVE"
                and other["variant"] == store["cluster"]
                and other["id"] != planogram["id"]
            ):
                installed = other
                break
    target_lines = [l for l in db.lines.values() if l["planogram_id"] == planogram["id"]]
    if installed is None:
        product_changes = len(target_lines)
    else:
        installed_pids = {
            l["product_id"] for l in db.lines.values()
            if l["planogram_id"] == installed["id"]
        }
        product_changes = sum(
            1 for l in target_lines if l["product_id"] not in installed_pids
        )
    raw = (
        Decimal(planogram["total_facings"]) * Decimal("0.05")
        + Decimal(product_changes) * Decimal("0.25")
    )
    return round_half_up(raw, 1)


def recompute_planogram(planogram):
    """Recompute header aggregates from lines; bumps planogram version (PRD §2.4)."""
    pgs_lines = [l for l in db.lines.values() if l["planogram_id"] == planogram["id"]]
    planogram["total_facings"] = sum(l["facings"] for l in pgs_lines)
    planogram["total_capacity_units"] = sum(l["capacity_units"] for l in pgs_lines)
    category = db.categories.get(planogram["category_id"])
    available = Decimal(category["total_linear_feet"]) * 12
    used = Decimal(0)
    for line in pgs_lines:
        product = db.products.get(line["product_id"])
        if product and product["status"] in ("LISTED", "DISCONTINUING"):
            used += Decimal(line["facings"]) * Decimal(repr(product["width_in"]))
    if available == 0:
        planogram["shelf_utilization_pct"] = 0.0
    else:
        planogram["shelf_utilization_pct"] = round_half_up(100 * used / available, 1)
    touch(planogram)
    # Live labor recompute for PROPOSED reset projects targeting this planogram.
    for project in db.projects.values():
        if project["planogram_id"] == planogram["id"] and project["status"] == "PROPOSED":
            project["labor_hours_estimated"] = compute_labor(project, planogram)
            touch(project)


def shelf_shares(planogram, supplier_id):
    """(own_share, rival_share) of shelf inches within one planogram."""
    own = Decimal(0)
    total = Decimal(0)
    for line in db.lines.values():
        if line["planogram_id"] != planogram["id"]:
            continue
        product = db.products.get(line["product_id"])
        if product is None:
            continue
        w = Decimal(line["facings"]) * Decimal(repr(product["width_in"]))
        total += w
        if product["supplier_id"] == supplier_id:
            own += w
    if total == 0:
        return Decimal(0), Decimal(0)
    return own / total, (total - own) / total


def compute_coi(deal):
    """Conflict-of-interest flag (PRD §3.8)."""
    supplier = db.suppliers.get(deal["supplier_id"])
    if supplier is None:
        return "NONE"
    cid = deal["category_id"]
    if supplier["is_captain"] and supplier.get("captain_category_id") == cid:
        # Captain funding its own category — compare shelf share vs prior ACTIVE.
        current_candidates = [
            p for p in db.planograms.values()
            if p["category_id"] == cid and p["status"] in ("APPROVED", "ACTIVE")
        ]
        if not current_candidates:
            return "NONE"
        current = max(current_candidates, key=lambda p: p["_seq"])
        priors = [
            p for p in db.planograms.values()
            if p["category_id"] == cid
            and p["status"] == "ACTIVE"
            and p["id"] != current["id"]
        ]
        if not priors:
            return "NONE"
        prior = max(priors, key=lambda p: p["_seq"])
        own_cur, riv_cur = shelf_shares(current, supplier["id"])
        own_pri, riv_pri = shelf_shares(prior, supplier["id"])
        if own_cur > own_pri and riv_cur < riv_pri:
            return "CAPTAIN_SELF_DEALING"
        return "NONE"
    if supplier["is_captain"]:
        return "NONE"
    captain = None
    for cand in db.suppliers.values():
        if (
            cand["retailer_id"] == deal["retailer_id"]
            and cand["is_captain"]
            and cand.get("captain_category_id") == cid
        ):
            captain = cand
            break
    if captain is None:
        return "NONE"
    for planogram in db.planograms.values():
        if planogram["category_id"] != cid or planogram["status"] not in ("APPROVED", "ACTIVE"):
            continue
        for line in db.lines.values():
            if line["planogram_id"] != planogram["id"]:
                continue
            product = db.products.get(line["product_id"])
            if product and product["supplier_id"] == supplier["id"]:
                return "NONE"
    return "CAPTAIN_BLOCKING_RIVAL"


def intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open interval intersection: [a) ∩ [b) ≠ ∅."""
    return a_start < b_end and b_start < a_end


def fire_clock_transitions():
    """Fire every time-based transition whose moment has arrived (PRD §2.9)."""
    current = db.clock
    # DISCONTINUING -> DELISTED products
    for product in list(db.products.values()):
        if (
            product["status"] == "DISCONTINUING"
            and product.get("_disc_dt") is not None
            and product["_disc_dt"] <= current
        ):
            product["status"] = "DELISTED"
            touch(product)
            affected_planograms = []
            for line in list(db.lines.values()):
                if line["product_id"] != product["id"]:
                    continue
                planogram = db.planograms.get(line["planogram_id"])
                if planogram and planogram["status"] in ("DRAFT", "IN_REVIEW"):
                    affected_planograms.append(planogram)
                    del db.lines[line["id"]]
                # ACTIVE (and other) planograms keep the line — no auto-edit.
            for planogram in affected_planograms:
                recompute_planogram(planogram)
    # APPROVED -> ACTIVE funding deals at starts_at
    for deal in list(db.deals.values()):
        if deal["status"] == "APPROVED" and deal["_starts"] <= current:
            deal["status"] = "ACTIVE"
            touch(deal)
    # ACTIVE -> CLOSED funding deals at ends_at
    for deal in list(db.deals.values()):
        if deal["status"] == "ACTIVE" and deal["_ends"] <= current:
            deal["status"] = "CLOSED"
            touch(deal)
    # SCHEDULED -> IN_PROGRESS reset projects at scheduled_start
    for project in list(db.projects.values()):
        if project["status"] == "SCHEDULED" and project["_start"] <= current:
            project["status"] = "IN_PROGRESS"
            touch(project)


# ---------------------------------------------------------------------------
# Auth + RBAC
# ---------------------------------------------------------------------------

def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise e401()
    if role not in allowed_roles:
        raise e403(f"Role {role} is not permitted to invoke this endpoint")
    return user_id, role


def route(rule, methods, roles, **options):
    """Register a view with auth + RBAC + global lock + ApiError translation."""

    def decorator(fn):
        endpoint_name = fn.__name__ + "|" + rule + "|" + ",".join(methods)

        @wraps(fn)
        def wrapper(*args, **kwargs):
            with LOCK:
                user_id, role = authenticate(roles)
                return fn(user_id, role, *args, **kwargs)

        wrapper.__name__ = fn.__name__
        app = current_app_holder[0]
        app.add_url_rule(
            rule,
            endpoint=endpoint_name,
            view_func=wrapper,
            methods=methods,
            strict_slashes=False,
            **options,
        )
        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Path resolvers (left-to-right within retailer scope, PRD §2.5)
# ---------------------------------------------------------------------------

def resolve_retailer(rid):
    retailer = db.retailers.get(rid)
    if retailer is None:
        raise e404("Retailer not found")
    return retailer


def resolve_category(rid, cid):
    resolve_retailer(rid)
    category = db.categories.get(cid)
    if category is None or category["retailer_id"] != rid:
        raise e404("Category not found")
    return category


def resolve_supplier(rid, sid):
    resolve_retailer(rid)
    supplier = db.suppliers.get(sid)
    if supplier is None or supplier["retailer_id"] != rid:
        raise e404("Supplier not found")
    return supplier


def resolve_product(rid, pid):
    resolve_retailer(rid)
    product = db.products.get(pid)
    if product is None or product["retailer_id"] != rid:
        raise e404("Product not found")
    return product


def resolve_planogram(rid, cid, pid):
    category = resolve_category(rid, cid)
    planogram = db.planograms.get(pid)
    if planogram is None or planogram["category_id"] != category["id"]:
        raise e404("Planogram not found")
    return category, planogram


def resolve_line(rid, cid, pid, lid):
    category, planogram = resolve_planogram(rid, cid, pid)
    line = db.lines.get(lid)
    if line is None or line["planogram_id"] != planogram["id"]:
        raise e404("Planogram line not found")
    return category, planogram, line


def resolve_store(rid, sid):
    resolve_retailer(rid)
    store = db.stores.get(sid)
    if store is None or store["retailer_id"] != rid:
        raise e404("Store not found")
    return store


def resolve_audit(rid, sid, aid):
    store = resolve_store(rid, sid)
    audit = db.audits.get(aid)
    if audit is None or audit["store_id"] != store["id"]:
        raise e404("Audit event not found")
    return store, audit


def resolve_deal(rid, fdid):
    resolve_retailer(rid)
    deal = db.deals.get(fdid)
    if deal is None or deal["retailer_id"] != rid:
        raise e404("Funding deal not found")
    return deal


def resolve_project(rid, cid, rpid):
    category = resolve_category(rid, cid)
    project = db.projects.get(rpid)
    if project is None or project["category_id"] != category["id"]:
        raise e404("Reset project not found")
    return category, project


def resolve_crew(rid, rcid):
    resolve_retailer(rid)
    crew = db.crews.get(rcid)
    if crew is None or crew["retailer_id"] != rid:
        raise e404("Reset crew not found")
    return crew


def resolve_assignment(rid, cid, rpid, raid):
    category, project = resolve_project(rid, cid, rpid)
    assignment = db.assignments.get(raid)
    if assignment is None or assignment["reset_project_id"] != project["id"]:
        raise e404("Reset assignment not found")
    return category, project, assignment


# ---------------------------------------------------------------------------
# Payload validation helpers (ERR_INVALID_REQUEST, PRD §2.8)
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise e400("Request body must be a JSON object")
    return data


def required(data, field):
    if field not in data or data[field] is None:
        raise e400(f"Missing required field: {field}")
    return data[field]


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise e400(f"Field '{field}' must be a non-empty string")
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise e400(f"Field '{field}' must be an integer")
    return value


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise e400(f"Field '{field}' must be a number")
    return value


def as_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise e400(f"Field '{field}' must be one of {sorted(allowed)}")
    return value


def optional_str(data, field):
    if field in data and data[field] is not None:
        return as_str(data[field], field)
    return None


def occ_precheck(data, field, current_version):
    """Stage-4 OCC check (PRD §2.8): runs before state validation when the
    expected-version field is present and well typed."""
    if field in data and data[field] is not None:
        value = data[field]
        if isinstance(value, bool) or not isinstance(value, int):
            return  # wrong type -> reported at payload stage as 400
        if value != current_version:
            raise ApiError(
                "ERR_STALE_VERSION",
                412,
                f"{field} {value} does not match current version {current_version}",
            )


def occ_required(data, field):
    """Payload-stage requirement of the OCC field (non-optional, PRD §2.7)."""
    return as_int(required(data, field), field)


def pagination_params():
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise e400("Query parameter 'limit' must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise e400("Query parameter 'offset' must be an integer")
    if limit < 1 or limit > 100:
        raise e400("Query parameter 'limit' must be between 1 and 100")
    if offset < 0:
        raise e400("Query parameter 'offset' must be >= 0")
    return limit, offset


def paginated(entities):
    ordered = sorted(entities, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    limit, offset = pagination_params()
    page = [pub(e) for e in ordered[offset:offset + limit]]
    return success_list(page, total, limit, offset)


def matches(entity, **filters):
    for key, value in filters.items():
        if value is not None and entity.get(key) != value:
            return False
    return True


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

current_app_holder = []


def build_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    current_app_holder.append(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(e404())

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(e404())

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        import traceback

        traceback.print_exc()
        return error_response(
            ApiError("ERR_VALIDATION", 422, f"Unexpected server error: {err}")
        )

    register_routes()
    return app


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def register_routes():
    retailer_read = ALL_ROLES  # GET /retailers/{id}
    catalog_read = ALL_ROLES  # categories / products / planograms / lines / stores
    supplier_read = {"PlatformAdmin", "RetailerAdmin", "CategoryManager", "CategoryCaptain"}
    audit_read = {"PlatformAdmin", "RetailerAdmin", "CategoryManager", "FieldAuditor", "AuditReviewer"}
    funding_read = supplier_read
    project_read = {"PlatformAdmin", "RetailerAdmin", "CategoryManager", "ResetCoordinator"}
    crew_read = {"PlatformAdmin", "RetailerAdmin", "ResetCoordinator"}
    space_roles = {"CategoryManager", "CategoryCaptain", "RetailerAdmin"}

    # =======================================================================
    # Retailer
    # =======================================================================

    @route("/retailers", ["POST"], {"PlatformAdmin"})
    def create_retailer(user_id, role):
        data = body()
        name = as_str(required(data, "name"), "name")
        threshold = data.get("compliance_threshold_pct", None)
        if threshold is None:
            threshold = DEFAULT_COMPLIANCE_THRESHOLD_PCT
        else:
            threshold = as_int(threshold, "compliance_threshold_pct")
        retailer = new_entity(
            name=name, status="ACTIVE", compliance_threshold_pct=threshold
        )
        db.retailers[retailer["id"]] = retailer
        return success_object(pub(retailer), 201)

    @route("/retailers/<rid>", ["GET"], retailer_read)
    def get_retailer(user_id, role, rid):
        retailer = resolve_retailer(rid)
        return success_object(pub(retailer))

    # =======================================================================
    # Category
    # =======================================================================

    @route("/retailers/<rid>/categories", ["POST"], {"CategoryManager"})
    def create_category(user_id, role, rid):
        resolve_retailer(rid)
        data = body()
        code = as_str(required(data, "code"), "code")
        cat_role = as_enum(required(data, "role"), "role", CATEGORY_ROLES)
        sales = as_int(required(data, "annual_sales_cents"), "annual_sales_cents")
        feet = as_int(required(data, "total_linear_feet"), "total_linear_feet")
        for existing in db.categories.values():
            if existing["retailer_id"] == rid and existing["code"] == code:
                raise e422(f"Category code '{code}' already exists in this retailer")
        category = new_entity(
            retailer_id=rid,
            code=code,
            role=cat_role,
            annual_sales_cents=sales,
            total_linear_feet=feet,
            status="OPEN",
            active_planogram_id=None,
        )
        db.categories[category["id"]] = category
        return success_object(pub(category), 201)

    @route("/retailers/<rid>/categories", ["GET"], catalog_read)
    def list_categories(user_id, role, rid):
        resolve_retailer(rid)
        items = [c for c in db.categories.values() if c["retailer_id"] == rid]
        return paginated(items)

    @route("/retailers/<rid>/categories/<cid>", ["GET"], catalog_read)
    def get_category(user_id, role, rid, cid):
        category = resolve_category(rid, cid)
        return success_object(pub(category))

    @route("/retailers/<rid>/categories/<cid>/lock", ["POST"], {"CategoryManager"})
    def lock_category(user_id, role, rid, cid):
        category = resolve_category(rid, cid)
        if category["status"] != "OPEN":
            raise e409("Only an OPEN category can be locked")
        category["status"] = "LOCKED"
        touch(category)
        return success_object(pub(category))

    @route("/retailers/<rid>/categories/<cid>/unlock", ["POST"], {"CategoryManager"})
    def unlock_category(user_id, role, rid, cid):
        category = resolve_category(rid, cid)
        if category["status"] != "LOCKED":
            raise e409("Only a LOCKED category can be unlocked")
        category["status"] = "OPEN"
        touch(category)
        return success_object(pub(category))

    @route("/retailers/<rid>/categories/<cid>/archive", ["POST"], {"CategoryManager"})
    def archive_category(user_id, role, rid, cid):
        category = resolve_category(rid, cid)
        if category["status"] != "OPEN":
            raise e409("Only an OPEN category can be archived")
        for planogram in db.planograms.values():
            if (
                planogram["category_id"] == cid
                and planogram["status"] in PLANOGRAM_OPEN_STATUSES
            ):
                raise ApiError(
                    "ERR_CATEGORY_HAS_OPEN_WORK",
                    422,
                    "Category has a planogram in a non-terminal state",
                )
        for project in db.projects.values():
            if (
                project["category_id"] == cid
                and project["status"] in PROJECT_OPEN_STATUSES
            ):
                raise ApiError(
                    "ERR_CATEGORY_HAS_OPEN_WORK",
                    422,
                    "Category has a reset project in a non-terminal state",
                )
        category["status"] = "ARCHIVED"
        touch(category)
        for product in db.products.values():
            if product["category_id"] == cid and product["status"] == "LISTED":
                product["status"] = "DISCONTINUING"
                product["_disc_dt"] = now()
                product["discontinuation_effective_date"] = fmt_dt(now())
                touch(product)
        return success_object(pub(category))

    @route("/retailers/<rid>/categories/<cid>/space-to-sales", ["GET"], space_roles)
    def space_to_sales(user_id, role, rid, cid):
        category = resolve_category(rid, cid)
        mode = request.args.get("mode")
        active = [
            p for p in db.planograms.values()
            if p["category_id"] == category["id"] and p["status"] == "ACTIVE"
        ]
        rows = []
        for planogram in sorted(active, key=lambda p: p["_seq"]):
            for line in sorted(
                (l for l in db.lines.values() if l["planogram_id"] == planogram["id"]),
                key=lambda l: l["_seq"],
            ):
                product = db.products.get(line["product_id"])
                if product and product["status"] == "LISTED":
                    rows.append((line, product))
        total_width = sum(
            Decimal(l["facings"]) * Decimal(repr(p["width_in"])) for l, p in rows
        )
        total_demand = sum(Decimal(p["weekly_demand_units"]) for l, p in rows)
        entries = []
        for line, product in rows:
            width = Decimal(line["facings"]) * Decimal(repr(product["width_in"]))
            demand = Decimal(product["weekly_demand_units"])
            space_share = (
                round_half_up(100 * width / total_width, 2) if total_width > 0 else 0.0
            )
            sales_share = (
                round_half_up(100 * demand / total_demand, 2) if total_demand > 0 else 0.0
            )
            entry = {
                "planogram_line_id": line["id"],
                "product_id": product["id"],
                "space_share_pct": space_share,
                "sales_share_pct": sales_share,
            }
            if mode == "indexed":
                if sales_share == 0:
                    entry["gap_ratio"] = INDEXED_ZERO_SALES_SENTINEL
                else:
                    entry["gap_ratio"] = round_half_up(
                        Decimal(repr(space_share)) / Decimal(repr(sales_share)), 2
                    )
            else:
                entry["gap_pct"] = round_half_up(
                    Decimal(repr(space_share)) - Decimal(repr(sales_share)), 2
                )
            entries.append(entry)
        return success_object({"lines": entries})

    # =======================================================================
    # Supplier
    # =======================================================================

    @route("/retailers/<rid>/suppliers", ["POST"], {"RetailerAdmin"})
    def create_supplier(user_id, role, rid):
        resolve_retailer(rid)
        data = body()
        name = as_str(required(data, "name"), "name")
        supplier = new_entity(
            retailer_id=rid, name=name, is_captain=False, captain_category_id=None
        )
        db.suppliers[supplier["id"]] = supplier
        return success_object(pub(supplier), 201)

    @route("/retailers/<rid>/suppliers", ["GET"], supplier_read)
    def list_suppliers(user_id, role, rid):
        resolve_retailer(rid)
        items = [s for s in db.suppliers.values() if s["retailer_id"] == rid]
        return paginated(items)

    @route("/retailers/<rid>/suppliers/<sid>", ["GET"], supplier_read)
    def get_supplier(user_id, role, rid, sid):
        supplier = resolve_supplier(rid, sid)
        return success_object(pub(supplier))

    @route("/retailers/<rid>/suppliers/<sid>/appoint-captain", ["POST"], {"RetailerAdmin"})
    def appoint_captain(user_id, role, rid, sid):
        supplier = resolve_supplier(rid, sid)
        data = body()
        category_id = as_str(required(data, "category_id"), "category_id")
        category = db.categories.get(category_id)
        if category is None or category["retailer_id"] != rid:
            raise e422("Referenced category does not exist in this retailer")
        # Single-captain invariant: clear the outgoing captain of this category.
        for other in db.suppliers.values():
            if (
                other["retailer_id"] == rid
                and other["id"] != supplier["id"]
                and other.get("captain_category_id") == category_id
                and other["is_captain"]
            ):
                other["is_captain"] = False
                other["captain_category_id"] = None
                touch(other)
        supplier["is_captain"] = True
        supplier["captain_category_id"] = category_id
        touch(supplier)
        # Captainship change recomputes coi_flag on PROPOSED/APPROVED deals.
        for deal in db.deals.values():
            if deal["category_id"] == category_id and deal["status"] in ("PROPOSED", "APPROVED"):
                deal["coi_flag"] = compute_coi(deal)
                touch(deal)
        return success_object(pub(supplier))

    # =======================================================================
    # Product
    # =======================================================================

    @route("/retailers/<rid>/products", ["POST"], {"CategoryManager", "CategoryCaptain"})
    def create_product(user_id, role, rid):
        resolve_retailer(rid)
        data = body()
        category_id = as_str(required(data, "category_id"), "category_id")
        supplier_id = as_str(required(data, "supplier_id"), "supplier_id")
        sku = as_str(required(data, "sku"), "sku")
        width = as_number(required(data, "width_in"), "width_in")
        cost = as_int(required(data, "unit_cost_cents"), "unit_cost_cents")
        weekly = as_int(required(data, "weekly_demand_units"), "weekly_demand_units")
        category = db.categories.get(category_id)
        if category is None or category["retailer_id"] != rid:
            raise e422("Referenced category does not exist in this retailer")
        supplier = db.suppliers.get(supplier_id)
        if supplier is None or supplier["retailer_id"] != rid:
            raise e422("Referenced supplier does not exist in this retailer")
        for existing in db.products.values():
            if existing["retailer_id"] == rid and existing["sku"] == sku:
                raise e422(f"Product sku '{sku}' already exists in this retailer")
        product = new_entity(
            retailer_id=rid,
            category_id=category_id,
            supplier_id=supplier_id,
            sku=sku,
            width_in=width,
            unit_cost_cents=cost,
            weekly_demand_units=weekly,
            status="CANDIDATE",
            discontinuation_effective_date=None,
            _disc_dt=None,
        )
        db.products[product["id"]] = product
        return success_object(pub(product), 201)

    @route("/retailers/<rid>/products", ["GET"], catalog_read)
    def list_products(user_id, role, rid):
        resolve_retailer(rid)
        items = [
            p for p in db.products.values()
            if p["retailer_id"] == rid
            and matches(
                p,
                category_id=request.args.get("category_id"),
                supplier_id=request.args.get("supplier_id"),
                status=request.args.get("status"),
            )
        ]
        return paginated(items)

    @route("/retailers/<rid>/products/<pid>", ["GET"], catalog_read)
    def get_product(user_id, role, rid, pid):
        product = resolve_product(rid, pid)
        return success_object(pub(product))

    @route("/retailers/<rid>/products/<pid>/list", ["POST"], {"CategoryManager"})
    def cut_in_product(user_id, role, rid, pid):
        product = resolve_product(rid, pid)
        if product["status"] != "CANDIDATE":
            raise e409("Only a CANDIDATE product can be cut in")
        category = db.categories[product["category_id"]]
        if category["status"] != "OPEN":
            raise ApiError(
                "ERR_CATEGORY_LOCKED", 409,
                "Category must be OPEN to cut in a product",
            )
        product["status"] = "LISTED"
        touch(product)
        return success_object(pub(product))

    @route("/retailers/<rid>/products/<pid>/discontinue", ["POST"], {"CategoryManager"})
    def discontinue_product(user_id, role, rid, pid):
        product = resolve_product(rid, pid)
        data = body()
        occ_precheck(data, "expected_product_version", product["version"])
        if product["status"] != "LISTED":
            raise e409("Only a LISTED product can be discontinued")
        occ_required(data, "expected_product_version")
        effective = parse_dt(
            required(data, "discontinuation_effective_date"),
            "discontinuation_effective_date",
        )
        if effective <= now():
            raise ApiError(
                "ERR_DISCONTINUATION_DATE_PAST", 422,
                "discontinuation_effective_date must lie strictly in the future",
            )
        product["status"] = "DISCONTINUING"
        product["_disc_dt"] = effective
        product["discontinuation_effective_date"] = fmt_dt(effective)
        touch(product)
        # Ripple into drafts: recompute dos/flags on DRAFT / IN_REVIEW lines.
        for line in db.lines.values():
            if line["product_id"] != product["id"]:
                continue
            planogram = db.planograms.get(line["planogram_id"])
            if planogram and planogram["status"] in ("DRAFT", "IN_REVIEW"):
                new_dos = compute_dos(product, line["capacity_units"])
                new_flag = dos_flag_for(new_dos)
                if new_dos != line["days_of_supply"] or new_flag != line["dos_flag"]:
                    line["days_of_supply"] = new_dos
                    line["dos_flag"] = new_flag
                    touch(line)
        return success_object(pub(product))

    @route("/retailers/<rid>/products/<pid>/cancel-discontinuation", ["POST"], {"CategoryManager"})
    def cancel_discontinuation(user_id, role, rid, pid):
        product = resolve_product(rid, pid)
        if product["status"] != "DISCONTINUING":
            raise e409("Only a DISCONTINUING product can have its discontinuation cancelled")
        product["status"] = "LISTED"
        product["_disc_dt"] = None
        product["discontinuation_effective_date"] = None
        touch(product)
        return success_object(pub(product))

    @route("/retailers/<rid>/products/<pid>/relist", ["POST"], {"CategoryManager"})
    def relist_product(user_id, role, rid, pid):
        product = resolve_product(rid, pid)
        if product["status"] != "DELISTED":
            raise e409("Only a DELISTED product can be relisted")
        product["status"] = "CANDIDATE"
        touch(product)
        return success_object(pub(product))

    # =======================================================================
    # Planogram
    # =======================================================================

    @route(
        "/retailers/<rid>/categories/<cid>/planograms",
        ["POST"], {"CategoryCaptain", "CategoryManager"},
    )
    def create_planogram(user_id, role, rid, cid):
        category = resolve_category(rid, cid)
        data = body()
        name = as_str(required(data, "name"), "name")
        variant = as_enum(required(data, "variant"), "variant", VARIANTS)
        note = optional_str(data, "version_note")
        planogram = new_entity(
            category_id=category["id"],
            name=name,
            variant=variant,
            status="DRAFT",
            version_note=note,
            total_facings=0,
            total_capacity_units=0,
            shelf_utilization_pct=0.0,
            submitted_by_captain_supplier_id=None,
            _was_active=False,
        )
        db.planograms[planogram["id"]] = planogram
        return success_object(pub(planogram), 201)

    @route("/retailers/<rid>/categories/<cid>/planograms", ["GET"], catalog_read)
    def list_planograms(user_id, role, rid, cid):
        category = resolve_category(rid, cid)
        items = [
            p for p in db.planograms.values()
            if p["category_id"] == category["id"]
            and matches(
                p,
                variant=request.args.get("variant"),
                status=request.args.get("status"),
            )
        ]
        return paginated(items)

    @route("/retailers/<rid>/categories/<cid>/planograms/<pid>", ["GET"], catalog_read)
    def get_planogram(user_id, role, rid, cid, pid):
        _, planogram = resolve_planogram(rid, cid, pid)
        return success_object(pub(planogram))

    @route(
        "/retailers/<rid>/categories/<cid>/planograms/<pid>/submit",
        ["POST"], {"CategoryCaptain"},
    )
    def submit_planogram(user_id, role, rid, cid, pid):
        category, planogram = resolve_planogram(rid, cid, pid)
        if planogram["status"] != "DRAFT":
            raise e409("Only a DRAFT planogram can be submitted")
        if category["status"] != "OPEN":
            raise ApiError(
                "ERR_CATEGORY_LOCKED", 409,
                "Category must be OPEN to submit a planogram",
            )
        lines = [l for l in db.lines.values() if l["planogram_id"] == planogram["id"]]
        if not lines:
            raise ApiError(
                "ERR_PLANOGRAM_INVALID", 422,
                "Planogram must contain at least one line",
            )
        if planogram["shelf_utilization_pct"] > 100:
            raise ApiError(
                "ERR_PLANOGRAM_INVALID", 422,
                "shelf_utilization_pct must not exceed 100 percent",
            )
        for line in lines:
            product = db.products.get(line["product_id"])
            if product and product["status"] == "DELISTED":
                raise ApiError(
                    "ERR_PLANOGRAM_INVALID", 422,
                    "Planogram references a DELISTED product",
                )
        planogram["status"] = "IN_REVIEW"
        planogram["submitted_by_captain_supplier_id"] = user_id
        touch(planogram)
        return success_object(pub(planogram))

    @route(
        "/retailers/<rid>/categories/<cid>/planograms/<pid>/approve",
        ["POST"], {"CategoryManager"},
    )
    def approve_planogram(user_id, role, rid, cid, pid):
        category, planogram = resolve_planogram(rid, cid, pid)
        if planogram["status"] != "IN_REVIEW":
            raise e409("Only an IN_REVIEW planogram can be approved")
        # Segregation of duties is evaluated before the assortment screens.
        if planogram.get("submitted_by_captain_supplier_id") == user_id:
            raise ApiError(
                "ERR_SELF_APPROVAL_FORBIDDEN", 422,
                "Approver must differ from the submitting captain (segregation of duties)",
            )
        lines = [l for l in db.lines.values() if l["planogram_id"] == planogram["id"]]
        # Assortment screens (after SoD per §2.8/§3.5): understock first.
        if category["role"] != "CONVENIENCE":
            for line in lines:
                if line["dos_flag"] == "UNDERSTOCK":
                    raise ApiError(
                        "ERR_UNDERSTOCK_NOT_ALLOWED", 422,
                        "Understock lines are not allowed outside CONVENIENCE categories",
                    )
        for line in lines:
            product = db.products.get(line["product_id"])
            if product and product["status"] == "DELISTED":
                raise e422("Planogram references a DELISTED product")
        planogram["status"] = "APPROVED"
        touch(planogram)
        # Finalize days-of-supply: snap down to the 0.5-day grid.
        for line in lines:
            finalized = snap_down_half_day(line["days_of_supply"])
            new_flag = dos_flag_for(finalized)
            if finalized != line["days_of_supply"] or new_flag != line["dos_flag"]:
                line["days_of_supply"] = finalized
                line["dos_flag"] = new_flag
                touch(line)
        # Approval recomputes coi_flag on PROPOSED funding deals in the category.
        for deal in db.deals.values():
            if deal["category_id"] == category["id"] and deal["status"] == "PROPOSED":
                deal["coi_flag"] = compute_coi(deal)
                touch(deal)
        return success_object(pub(planogram))

    @route(
        "/retailers/<rid>/categories/<cid>/planograms/<pid>/reject",
        ["POST"], {"CategoryManager"},
    )
    def reject_planogram(user_id, role, rid, cid, pid):
        _, planogram = resolve_planogram(rid, cid, pid)
        if planogram["status"] != "IN_REVIEW":
            raise e409("Only an IN_REVIEW planogram can be rejected")
        planogram["status"] = "REJECTED"
        touch(planogram)
        return success_object(pub(planogram))

    @route(
        "/retailers/<rid>/categories/<cid>/planograms/<pid>/return-to-draft",
        ["POST"], {"CategoryCaptain"},
    )
    def return_planogram_to_draft(user_id, role, rid, cid, pid):
        _, planogram = resolve_planogram(rid, cid, pid)
        if planogram["status"] == "IN_REVIEW":
            pass
        elif planogram["status"] == "APPROVED" and not planogram.get("_was_active"):
            pass
        else:
            raise e409("Planogram cannot return to DRAFT from its current state")
        planogram["status"] = "DRAFT"
        touch(planogram)
        return success_object(pub(planogram))

    @route(
        "/retailers/<rid>/categories/<cid>/planograms/<pid>/activate",
        ["POST"], {"CategoryManager"},
    )
    def activate_planogram(user_id, role, rid, cid, pid):
        category, planogram = resolve_planogram(rid, cid, pid)
        data = body()
        occ_precheck(data, "expected_category_version", category["version"])
        if planogram["status"] != "APPROVED":
            raise e409("Only an APPROVED planogram can be activated")
        if category["status"] != "OPEN":
            raise ApiError(
                "ERR_CATEGORY_LOCKED", 409,
                "Category must be OPEN to activate a planogram",
            )
        occ_required(data, "expected_category_version")
        # Supersede the previously ACTIVE planogram of the same (category, variant).
        for other in list(db.planograms.values()):
            if (
                other["category_id"] == category["id"]
                and other["variant"] == planogram["variant"]
                and other["status"] == "ACTIVE"
                and other["id"] != planogram["id"]
            ):
                other["status"] = "SUPERSEDED"
                touch(other)
                if category.get("active_planogram_id") == other["id"]:
                    category["active_planogram_id"] = None
                # Depth-2 cascade: cancel open reset projects, release crews.
                for project in db.projects.values():
                    if (
                        project["planogram_id"] == other["id"]
                        and project["status"] in ("PROPOSED", "SCHEDULED")
                    ):
                        project["status"] = "CANCELLED"
                        touch(project)
                        for assignment in db.assignments.values():
                            if (
                                assignment["reset_project_id"] == project["id"]
                                and assignment["status"] == "ASSIGNED"
                            ):
                                assignment["status"] = "RELEASED"
                                touch(assignment)
        planogram["status"] = "ACTIVE"
        planogram["_was_active"] = True
        touch(planogram)
        if planogram["variant"] == "BASE":
            category["active_planogram_id"] = planogram["id"]
        touch(category)
        return success_object(pub(planogram))

    # =======================================================================
    # PlanogramLine
    # =======================================================================

    @route(
        "/retailers/<rid>/categories/<cid>/planograms/<pid>/lines",
        ["POST"], {"CategoryCaptain", "CategoryManager"},
    )
    def create_planogram_line(user_id, role, rid, cid, pid):
        category, planogram = resolve_planogram(rid, cid, pid)
        if planogram["status"] != "DRAFT":
            raise e409("Lines can only be added to a DRAFT planogram")
        data = body()
        product_id = as_str(required(data, "product_id"), "product_id")
        position_index = as_int(required(data, "position_index"), "position_index")
        facings = as_int(required(data, "facings"), "facings")
        capacity_units = as_int(required(data, "capacity_units"), "capacity_units")
        # Product-eligibility screen runs before the line's own number checks.
        product = db.products.get(product_id)
        if (
            product is None
            or product["retailer_id"] != rid
            or product["status"] not in ("LISTED", "DISCONTINUING")
        ):
            raise ApiError(
                "ERR_PRODUCT_NOT_LISTABLE", 422,
                "Referenced product must exist and be LISTED or DISCONTINUING",
            )
        if facings < 1:
            raise ApiError("ERR_LINE_INVALID", 422, "facings must be at least 1")
        if capacity_units < facings:
            raise ApiError(
                "ERR_LINE_INVALID", 422, "capacity_units must be at least facings"
            )
        for existing in db.lines.values():
            if (
                existing["planogram_id"] == planogram["id"]
                and existing["position_index"] == position_index
            ):
                raise ApiError(
                    "ERR_LINE_INVALID", 422,
                    "position_index already used in this planogram",
                )
        line = new_entity(
            planogram_id=planogram["id"],
            product_id=product_id,
            position_index=position_index,
            facings=facings,
            capacity_units=capacity_units,
        )
        line["days_of_supply"] = compute_dos(product, capacity_units)
        line["dos_flag"] = dos_flag_for(line["days_of_supply"])
        db.lines[line["id"]] = line
        recompute_planogram(planogram)
        return success_object(pub(line), 201)

    @route(
        "/retailers/<rid>/categories/<cid>/planograms/<pid>/lines",
        ["GET"], catalog_read,
    )
    def list_planogram_lines(user_id, role, rid, cid, pid):
        _, planogram = resolve_planogram(rid, cid, pid)
        items = [l for l in db.lines.values() if l["planogram_id"] == planogram["id"]]
        return paginated(items)

    @route(
        "/retailers/<rid>/categories/<cid>/planograms/<pid>/lines/<lid>",
        ["GET"], catalog_read,
    )
    def get_planogram_line(user_id, role, rid, cid, pid, lid):
        _, _, line = resolve_line(rid, cid, pid, lid)
        return success_object(pub(line))

    @route(
        "/retailers/<rid>/categories/<cid>/planograms/<pid>/lines/<lid>",
        ["DELETE"], {"CategoryCaptain", "CategoryManager"},
    )
    def delete_planogram_line(user_id, role, rid, cid, pid, lid):
        _, planogram, line = resolve_line(rid, cid, pid, lid)
        if planogram["status"] != "DRAFT":
            raise e409("Lines can only be deleted while the planogram is DRAFT")
        del db.lines[line["id"]]
        recompute_planogram(planogram)
        return "", 204

    # =======================================================================
    # Store
    # =======================================================================

    @route("/retailers/<rid>/stores", ["POST"], {"RetailerAdmin"})
    def create_store(user_id, role, rid):
        resolve_retailer(rid)
        data = body()
        store_code = as_str(required(data, "store_code"), "store_code")
        cluster = as_enum(required(data, "cluster"), "cluster", VARIANTS)
        for existing in db.stores.values():
            if existing["retailer_id"] == rid and existing["store_code"] == store_code:
                raise e422(f"Store code '{store_code}' already exists in this retailer")
        store = new_entity(retailer_id=rid, store_code=store_code, cluster=cluster)
        db.stores[store["id"]] = store
        return success_object(pub(store), 201)

    @route("/retailers/<rid>/stores", ["GET"], catalog_read)
    def list_stores(user_id, role, rid):
        resolve_retailer(rid)
        items = [
            s for s in db.stores.values()
            if s["retailer_id"] == rid and matches(s, cluster=request.args.get("cluster"))
        ]
        return paginated(items)

    @route("/retailers/<rid>/stores/<sid>", ["GET"], catalog_read)
    def get_store(user_id, role, rid, sid):
        store = resolve_store(rid, sid)
        return success_object(pub(store))

    # =======================================================================
    # AuditEvent
    # =======================================================================

    @route("/retailers/<rid>/stores/<sid>/audits", ["POST"], {"FieldAuditor"})
    def create_audit(user_id, role, rid, sid):
        store = resolve_store(rid, sid)
        data = body()
        planogram_id = as_str(required(data, "planogram_id"), "planogram_id")
        photo_url = as_str(required(data, "photo_url"), "photo_url")
        planogram = db.planograms.get(planogram_id)
        if planogram is None:
            raise e422("Referenced planogram does not exist in this retailer")
        owner_category = db.categories.get(planogram["category_id"])
        if owner_category is None or owner_category["retailer_id"] != rid:
            raise e422("Referenced planogram does not exist in this retailer")
        audit = new_entity(
            store_id=store["id"],
            planogram_id=planogram_id,
            photo_url=photo_url,
            submitted_by_role="FieldAuditor",
            status="SUBMITTED",
            matched_facings=None,
            total_facings_expected=planogram["total_facings"],
            compliance_score_pct=None,
            compliance_outcome=None,
        )
        db.audits[audit["id"]] = audit
        return success_object(pub(audit), 201)

    @route("/retailers/<rid>/stores/<sid>/audits", ["GET"], audit_read)
    def list_audits(user_id, role, rid, sid):
        store = resolve_store(rid, sid)
        items = [
            a for a in db.audits.values()
            if a["store_id"] == store["id"]
            and matches(a, status=request.args.get("status"))
        ]
        return paginated(items)

    @route("/retailers/<rid>/stores/<sid>/audits/<aid>", ["GET"], audit_read)
    def get_audit(user_id, role, rid, sid, aid):
        _, audit = resolve_audit(rid, sid, aid)
        return success_object(pub(audit))

    @route(
        "/retailers/<rid>/stores/<sid>/audits/<aid>/score",
        ["POST"], {"AuditReviewer"},
    )
    def score_audit(user_id, role, rid, sid, aid):
        store, audit = resolve_audit(rid, sid, aid)
        if audit["status"] != "SUBMITTED":
            raise e409("Only a SUBMITTED audit can be scored")
        data = body()
        matched = as_int(required(data, "matched_facings"), "matched_facings")
        expected = audit["total_facings_expected"] or 0
        if matched < 0 or matched > expected:
            raise ApiError(
                "ERR_AUDIT_SCORE_RANGE", 422,
                "matched_facings must lie in [0, total_facings_expected]",
            )
        planogram = db.planograms.get(audit["planogram_id"])
        if planogram is None or planogram["status"] not in ("ACTIVE", "SUPERSEDED"):
            raise e422("Audited planogram must be ACTIVE or SUPERSEDED at scoring time")
        retailer = db.retailers[rid]
        score = 0 if expected == 0 else (100 * matched) // expected
        threshold = retailer["compliance_threshold_pct"]
        if score >= threshold:
            outcome = "PASS"
        elif score >= threshold - COMPLIANCE_WARN_BELOW:
            outcome = "WARN"
        else:
            outcome = "FAIL"
        audit["status"] = "SCORED"
        audit["matched_facings"] = matched
        audit["compliance_score_pct"] = score
        audit["compliance_outcome"] = outcome
        touch(audit)
        if outcome == "FAIL" and planogram["status"] == "ACTIVE":
            start = datetime.combine(
                (now() + timedelta(days=1)).date(), dtime.min, tzinfo=timezone.utc
            )
            end = start + timedelta(days=FAIL_RESET_WINDOW_DAYS)
            project = new_entity(
                category_id=planogram["category_id"],
                planogram_id=planogram["id"],
                store_id=store["id"],
                scheduled_start=fmt_dt(start),
                scheduled_end=fmt_dt(end),
                status="PROPOSED",
                _start=start,
                _end=end,
            )
            project["labor_hours_estimated"] = compute_labor(project, planogram)
            db.projects[project["id"]] = project
        return success_object(pub(audit))

    @route(
        "/retailers/<rid>/stores/<sid>/audits/<aid>/reject",
        ["POST"], {"AuditReviewer"},
    )
    def reject_audit(user_id, role, rid, sid, aid):
        _, audit = resolve_audit(rid, sid, aid)
        if audit["status"] != "SUBMITTED":
            raise e409("Only a SUBMITTED audit can be rejected")
        audit["status"] = "REJECTED"
        touch(audit)
        return success_object(pub(audit))

    # =======================================================================
    # FundingDeal
    # =======================================================================

    @route("/retailers/<rid>/funding-deals", ["POST"], {"RetailerAdmin", "CategoryCaptain"})
    def create_funding_deal(user_id, role, rid):
        resolve_retailer(rid)
        data = body()
        category_id = as_str(required(data, "category_id"), "category_id")
        supplier_id = as_str(required(data, "supplier_id"), "supplier_id")
        amount = as_int(required(data, "amount_cents"), "amount_cents")
        starts = parse_dt(required(data, "starts_at"), "starts_at")
        ends = parse_dt(required(data, "ends_at"), "ends_at")
        category = db.categories.get(category_id)
        if category is None or category["retailer_id"] != rid:
            raise e422("Referenced category does not exist in this retailer")
        supplier = db.suppliers.get(supplier_id)
        if supplier is None or supplier["retailer_id"] != rid:
            raise e422("Referenced supplier does not exist in this retailer")
        deal = new_entity(
            retailer_id=rid,
            category_id=category_id,
            supplier_id=supplier_id,
            amount_cents=amount,
            starts_at=fmt_dt(starts),
            ends_at=fmt_dt(ends),
            status="PROPOSED",
            _starts=starts,
            _ends=ends,
        )
        deal["coi_flag"] = compute_coi(deal)
        db.deals[deal["id"]] = deal
        return success_object(pub(deal), 201)

    @route("/retailers/<rid>/funding-deals", ["GET"], funding_read)
    def list_funding_deals(user_id, role, rid):
        resolve_retailer(rid)
        items = [
            d for d in db.deals.values()
            if d["retailer_id"] == rid
            and matches(
                d,
                category_id=request.args.get("category_id"),
                supplier_id=request.args.get("supplier_id"),
                status=request.args.get("status"),
            )
        ]
        return paginated(items)

    @route("/retailers/<rid>/funding-deals/<fdid>", ["GET"], funding_read)
    def get_funding_deal(user_id, role, rid, fdid):
        deal = resolve_deal(rid, fdid)
        return success_object(pub(deal))

    @route("/retailers/<rid>/funding-deals/<fdid>/approve", ["POST"], {"RetailerAdmin"})
    def approve_funding_deal(user_id, role, rid, fdid):
        deal = resolve_deal(rid, fdid)
        data = body()
        occ_precheck(data, "expected_funding_deal_version", deal["version"])
        if deal["status"] != "PROPOSED":
            raise e409("Only a PROPOSED funding deal can be approved")
        occ_required(data, "expected_funding_deal_version")
        if deal["coi_flag"] == "CAPTAIN_BLOCKING_RIVAL":
            raise ApiError(
                "ERR_CAPTAIN_CONFLICT", 422,
                "Deal is flagged CAPTAIN_BLOCKING_RIVAL and cannot be approved",
            )
        deal["status"] = "APPROVED"
        touch(deal)
        return success_object(pub(deal))

    @route("/retailers/<rid>/funding-deals/<fdid>/reject", ["POST"], {"RetailerAdmin"})
    def reject_funding_deal(user_id, role, rid, fdid):
        deal = resolve_deal(rid, fdid)
        if deal["status"] != "PROPOSED":
            raise e409("Only a PROPOSED funding deal can be rejected")
        deal["status"] = "REJECTED"
        touch(deal)
        return success_object(pub(deal))

    # =======================================================================
    # ResetProject
    # =======================================================================

    @route(
        "/retailers/<rid>/categories/<cid>/reset-projects",
        ["POST"], {"ResetCoordinator", "CategoryManager"},
    )
    def create_reset_project(user_id, role, rid, cid):
        category = resolve_category(rid, cid)
        data = body()
        planogram_id = as_str(required(data, "planogram_id"), "planogram_id")
        store_id = as_str(required(data, "store_id"), "store_id")
        start = parse_dt(required(data, "scheduled_start"), "scheduled_start")
        end = parse_dt(required(data, "scheduled_end"), "scheduled_end")
        planogram = db.planograms.get(planogram_id)
        if planogram is None or planogram["category_id"] != category["id"]:
            raise e422("Referenced planogram does not exist in this category")
        store = db.stores.get(store_id)
        if store is None or store["retailer_id"] != rid:
            raise e422("Referenced store does not exist in this retailer")
        if not start < end:
            raise ApiError(
                "ERR_RESET_WINDOW_CONFLICT", 422,
                "scheduled_start must be strictly earlier than scheduled_end",
            )
        project = new_entity(
            category_id=category["id"],
            planogram_id=planogram_id,
            store_id=store_id,
            scheduled_start=fmt_dt(start),
            scheduled_end=fmt_dt(end),
            status="PROPOSED",
            _start=start,
            _end=end,
        )
        project["labor_hours_estimated"] = compute_labor(project, planogram)
        db.projects[project["id"]] = project
        return success_object(pub(project), 201)

    @route("/retailers/<rid>/categories/<cid>/reset-projects", ["GET"], project_read)
    def list_reset_projects(user_id, role, rid, cid):
        category = resolve_category(rid, cid)
        items = [
            p for p in db.projects.values()
            if p["category_id"] == category["id"]
            and matches(
                p,
                store_id=request.args.get("store_id"),
                status=request.args.get("status"),
            )
        ]
        return paginated(items)

    @route("/retailers/<rid>/categories/<cid>/reset-projects/<rpid>", ["GET"], project_read)
    def get_reset_project(user_id, role, rid, cid, rpid):
        _, project = resolve_project(rid, cid, rpid)
        return success_object(pub(project))

    @route(
        "/retailers/<rid>/categories/<cid>/reset-projects/<rpid>/schedule",
        ["POST"], {"ResetCoordinator"},
    )
    def schedule_reset_project(user_id, role, rid, cid, rpid):
        _, project = resolve_project(rid, cid, rpid)
        data = body()
        occ_precheck(data, "expected_reset_project_version", project["version"])
        if project["status"] != "PROPOSED":
            raise e409("Only a PROPOSED reset project can be scheduled")
        occ_required(data, "expected_reset_project_version")
        if not project["_start"] < project["_end"]:
            raise ApiError(
                "ERR_RESET_WINDOW_CONFLICT", 422,
                "scheduled_start must be strictly earlier than scheduled_end",
            )
        for other in db.projects.values():
            if (
                other["id"] != project["id"]
                and other["store_id"] == project["store_id"]
                and other["status"] in ("SCHEDULED", "IN_PROGRESS")
                and intervals_overlap(
                    project["_start"], project["_end"], other["_start"], other["_end"]
                )
            ):
                raise ApiError(
                    "ERR_RESET_WINDOW_CONFLICT", 422,
                    "Reset window overlaps another scheduled project at this store",
                )
        planogram = db.planograms.get(project["planogram_id"])
        if planogram is None or planogram["status"] not in ("APPROVED", "ACTIVE"):
            raise e422("Referenced planogram must be APPROVED or ACTIVE to schedule")
        project["status"] = "SCHEDULED"
        touch(project)
        return success_object(pub(project))

    @route(
        "/retailers/<rid>/categories/<cid>/reset-projects/<rpid>/complete",
        ["POST"], {"ResetCoordinator"},
    )
    def complete_reset_project(user_id, role, rid, cid, rpid):
        _, project = resolve_project(rid, cid, rpid)
        if project["status"] != "IN_PROGRESS":
            raise e409("Only an IN_PROGRESS reset project can be completed")
        assigned = [
            a for a in db.assignments.values()
            if a["reset_project_id"] == project["id"] and a["status"] == "ASSIGNED"
        ]
        if not assigned:
            raise e422("Project has no ASSIGNED crew assignment")
        project["status"] = "COMPLETED"
        touch(project)
        for assignment in assigned:
            assignment["status"] = "RELEASED"
            touch(assignment)
        return success_object(pub(project))

    @route(
        "/retailers/<rid>/categories/<cid>/reset-projects/<rpid>/cancel",
        ["POST"], {"ResetCoordinator"},
    )
    def cancel_reset_project(user_id, role, rid, cid, rpid):
        _, project = resolve_project(rid, cid, rpid)
        if project["status"] == "PROPOSED":
            project["status"] = "CANCELLED"
            touch(project)
        elif project["status"] == "SCHEDULED":
            project["status"] = "CANCELLED"
            touch(project)
            for assignment in db.assignments.values():
                if (
                    assignment["reset_project_id"] == project["id"]
                    and assignment["status"] == "ASSIGNED"
                ):
                    assignment["status"] = "RELEASED"
                    touch(assignment)
        else:
            raise e409("Only a PROPOSED or SCHEDULED reset project can be cancelled")
        return success_object(pub(project))

    # =======================================================================
    # ResetCrew
    # =======================================================================

    @route("/retailers/<rid>/reset-crews", ["POST"], {"ResetCoordinator"})
    def create_reset_crew(user_id, role, rid):
        resolve_retailer(rid)
        data = body()
        name = as_str(required(data, "name"), "name")
        cap = data.get("max_concurrent_projects", None)
        if cap is None:
            cap = DEFAULT_MAX_CONCURRENT
        else:
            cap = as_int(cap, "max_concurrent_projects")
        crew = new_entity(retailer_id=rid, name=name, max_concurrent_projects=cap)
        db.crews[crew["id"]] = crew
        return success_object(pub(crew), 201)

    @route("/retailers/<rid>/reset-crews", ["GET"], crew_read)
    def list_reset_crews(user_id, role, rid):
        resolve_retailer(rid)
        items = [c for c in db.crews.values() if c["retailer_id"] == rid]
        return paginated(items)

    @route("/retailers/<rid>/reset-crews/<rcid>", ["GET"], crew_read)
    def get_reset_crew(user_id, role, rid, rcid):
        crew = resolve_crew(rid, rcid)
        return success_object(pub(crew))

    # =======================================================================
    # ResetAssignment
    # =======================================================================

    @route(
        "/retailers/<rid>/categories/<cid>/reset-projects/<rpid>/assignments",
        ["POST"], {"ResetCoordinator"},
    )
    def create_reset_assignment(user_id, role, rid, cid, rpid):
        _, project = resolve_project(rid, cid, rpid)
        if project["status"] not in ("PROPOSED", "SCHEDULED"):
            raise e409("Crews can only be assigned to a PROPOSED or SCHEDULED project")
        data = body()
        crew_id = as_str(required(data, "crew_id"), "crew_id")
        start = parse_dt(required(data, "assigned_start"), "assigned_start")
        end = parse_dt(required(data, "assigned_end"), "assigned_end")
        crew = db.crews.get(crew_id)
        if crew is None or crew["retailer_id"] != rid:
            raise e422("Referenced crew does not exist in this retailer")
        if not start < end:
            raise ApiError(
                "ERR_CREW_OVERLAP", 422,
                "assigned_start must be strictly earlier than assigned_end",
            )
        if start < project["_start"] or end > project["_end"]:
            raise ApiError(
                "ERR_CREW_OVERLAP", 422,
                "Assigned window must lie inside the project's scheduled window",
            )
        crew_assignments = [
            a for a in db.assignments.values()
            if a["crew_id"] == crew_id and a["status"] == "ASSIGNED"
        ]
        for other in crew_assignments:
            if intervals_overlap(start, end, other["_start"], other["_end"]):
                raise ApiError(
                    "ERR_CREW_OVERLAP", 422,
                    "Assigned window overlaps another ASSIGNED assignment of this crew",
                )
        # Aggregate capacity: never more ASSIGNED at any instant than the cap.
        intervals = [(a["_start"], a["_end"]) for a in crew_assignments] + [(start, end)]
        points = sorted({p for iv in intervals for p in iv})
        for seg_start, seg_end in zip(points, points[1:]):
            count = sum(
                1 for iv_s, iv_e in intervals
                if iv_s <= seg_start and seg_end <= iv_e
            )
            if count > crew["max_concurrent_projects"]:
                raise ApiError(
                    "ERR_CREW_OVERLAP", 422,
                    "Crew concurrent-project cap would be exceeded",
                )
        assignment = new_entity(
            reset_project_id=project["id"],
            crew_id=crew_id,
            assigned_start=fmt_dt(start),
            assigned_end=fmt_dt(end),
            status="ASSIGNED",
            _start=start,
            _end=end,
        )
        db.assignments[assignment["id"]] = assignment
        return success_object(pub(assignment), 201)

    @route(
        "/retailers/<rid>/categories/<cid>/reset-projects/<rpid>/assignments",
        ["GET"], crew_read,
    )
    def list_reset_assignments(user_id, role, rid, cid, rpid):
        _, project = resolve_project(rid, cid, rpid)
        items = [
            a for a in db.assignments.values()
            if a["reset_project_id"] == project["id"]
        ]
        return paginated(items)

    @route(
        "/retailers/<rid>/categories/<cid>/reset-projects/<rpid>/assignments/<raid>",
        ["GET"], crew_read,
    )
    def get_reset_assignment(user_id, role, rid, cid, rpid, raid):
        _, _, assignment = resolve_assignment(rid, cid, rpid, raid)
        return success_object(pub(assignment))

    @route(
        "/retailers/<rid>/categories/<cid>/reset-projects/<rpid>/assignments/<raid>/release",
        ["POST"], {"ResetCoordinator"},
    )
    def release_reset_assignment(user_id, role, rid, cid, rpid, raid):
        _, _, assignment = resolve_assignment(rid, cid, rpid, raid)
        if assignment["status"] != "ASSIGNED":
            raise e409("Only an ASSIGNED assignment can be released")
        assignment["status"] = "RELEASED"
        touch(assignment)
        return success_object(pub(assignment))

    # =======================================================================
    # Flat filtered-list GETs (FK reverse reachability)
    # =======================================================================

    @route("/categories", ["GET"], catalog_read)
    def flat_list_categories(user_id, role):
        items = [
            c for c in db.categories.values()
            if matches(c, retailer_id=request.args.get("retailer_id"))
        ]
        return paginated(items)

    @route("/suppliers", ["GET"], supplier_read)
    def flat_list_suppliers(user_id, role):
        items = [
            s for s in db.suppliers.values()
            if matches(
                s,
                retailer_id=request.args.get("retailer_id"),
                captain_category_id=request.args.get("captain_category_id"),
            )
        ]
        return paginated(items)

    @route("/products", ["GET"], catalog_read)
    def flat_list_products(user_id, role):
        items = [
            p for p in db.products.values()
            if matches(
                p,
                retailer_id=request.args.get("retailer_id"),
                category_id=request.args.get("category_id"),
                supplier_id=request.args.get("supplier_id"),
                status=request.args.get("status"),
            )
        ]
        return paginated(items)

    @route("/planograms", ["GET"], catalog_read)
    def flat_list_planograms(user_id, role):
        items = [
            p for p in db.planograms.values()
            if matches(
                p,
                category_id=request.args.get("category_id"),
                submitted_by_captain_supplier_id=request.args.get(
                    "submitted_by_captain_supplier_id"
                ),
                variant=request.args.get("variant"),
                status=request.args.get("status"),
            )
        ]
        return paginated(items)

    @route("/planogram-lines", ["GET"], catalog_read)
    def flat_list_planogram_lines(user_id, role):
        items = [
            l for l in db.lines.values()
            if matches(
                l,
                planogram_id=request.args.get("planogram_id"),
                product_id=request.args.get("product_id"),
            )
        ]
        return paginated(items)

    @route("/stores", ["GET"], catalog_read)
    def flat_list_stores(user_id, role):
        items = [
            s for s in db.stores.values()
            if matches(
                s,
                retailer_id=request.args.get("retailer_id"),
                cluster=request.args.get("cluster"),
            )
        ]
        return paginated(items)

    @route("/audit-events", ["GET"], audit_read)
    def flat_list_audits(user_id, role):
        items = [
            a for a in db.audits.values()
            if matches(
                a,
                store_id=request.args.get("store_id"),
                planogram_id=request.args.get("planogram_id"),
                status=request.args.get("status"),
            )
        ]
        return paginated(items)

    @route("/funding-deals", ["GET"], funding_read)
    def flat_list_funding_deals(user_id, role):
        items = [
            d for d in db.deals.values()
            if matches(
                d,
                retailer_id=request.args.get("retailer_id"),
                category_id=request.args.get("category_id"),
                supplier_id=request.args.get("supplier_id"),
                status=request.args.get("status"),
            )
        ]
        return paginated(items)

    @route("/reset-projects", ["GET"], project_read)
    def flat_list_reset_projects(user_id, role):
        items = [
            p for p in db.projects.values()
            if matches(
                p,
                category_id=request.args.get("category_id"),
                planogram_id=request.args.get("planogram_id"),
                store_id=request.args.get("store_id"),
                status=request.args.get("status"),
            )
        ]
        return paginated(items)

    @route("/reset-crews", ["GET"], crew_read)
    def flat_list_reset_crews(user_id, role):
        items = [
            c for c in db.crews.values()
            if matches(c, retailer_id=request.args.get("retailer_id"))
        ]
        return paginated(items)

    @route("/reset-assignments", ["GET"], crew_read)
    def flat_list_reset_assignments(user_id, role):
        items = [
            a for a in db.assignments.values()
            if matches(
                a,
                reset_project_id=request.args.get("reset_project_id"),
                crew_id=request.args.get("crew_id"),
                status=request.args.get("status"),
            )
        ]
        return paginated(items)

    # =======================================================================
    # Flat single-resource GETs
    # =======================================================================

    @route("/categories/<cid>", ["GET"], catalog_read)
    def flat_get_category(user_id, role, cid):
        category = db.categories.get(cid)
        if category is None:
            raise e404("Category not found")
        return success_object(pub(category))

    @route("/suppliers/<sid>", ["GET"], supplier_read)
    def flat_get_supplier(user_id, role, sid):
        supplier = db.suppliers.get(sid)
        if supplier is None:
            raise e404("Supplier not found")
        return success_object(pub(supplier))

    @route("/products/<pid>", ["GET"], catalog_read)
    def flat_get_product(user_id, role, pid):
        product = db.products.get(pid)
        if product is None:
            raise e404("Product not found")
        return success_object(pub(product))

    @route("/planograms/<pid>", ["GET"], catalog_read)
    def flat_get_planogram(user_id, role, pid):
        planogram = db.planograms.get(pid)
        if planogram is None:
            raise e404("Planogram not found")
        return success_object(pub(planogram))

    @route("/planogram-lines/<lid>", ["GET"], catalog_read)
    def flat_get_planogram_line(user_id, role, lid):
        line = db.lines.get(lid)
        if line is None:
            raise e404("Planogram line not found")
        return success_object(pub(line))

    @route("/stores/<sid>", ["GET"], catalog_read)
    def flat_get_store(user_id, role, sid):
        store = db.stores.get(sid)
        if store is None:
            raise e404("Store not found")
        return success_object(pub(store))

    @route("/audit-events/<aid>", ["GET"], audit_read)
    def flat_get_audit(user_id, role, aid):
        audit = db.audits.get(aid)
        if audit is None:
            raise e404("Audit event not found")
        return success_object(pub(audit))

    @route("/funding-deals/<fdid>", ["GET"], funding_read)
    def flat_get_funding_deal(user_id, role, fdid):
        deal = db.deals.get(fdid)
        if deal is None:
            raise e404("Funding deal not found")
        return success_object(pub(deal))

    @route("/reset-projects/<rpid>", ["GET"], project_read)
    def flat_get_reset_project(user_id, role, rpid):
        project = db.projects.get(rpid)
        if project is None:
            raise e404("Reset project not found")
        return success_object(pub(project))

    @route("/reset-crews/<rcid>", ["GET"], crew_read)
    def flat_get_reset_crew(user_id, role, rcid):
        crew = db.crews.get(rcid)
        if crew is None:
            raise e404("Reset crew not found")
        return success_object(pub(crew))

    @route("/reset-assignments/<raid>", ["GET"], crew_read)
    def flat_get_reset_assignment(user_id, role, raid):
        assignment = db.assignments.get(raid)
        if assignment is None:
            raise e404("Reset assignment not found")
        return success_object(pub(assignment))

    # =======================================================================
    # Logical clock (PRD §2.9)
    # =======================================================================

    @route("/retailers/<rid>/_clock/set_current_utc", ["POST"], {"PlatformAdmin"})
    def set_current_utc(user_id, role, rid):
        resolve_retailer(rid)
        data = body()
        target = parse_dt(required(data, "to_iso8601"), "to_iso8601")
        db.clock = target
        fire_clock_transitions()
        return success_object({"current_utc": fmt_dt(db.clock)})
