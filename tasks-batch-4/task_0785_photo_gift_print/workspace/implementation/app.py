"""Photo-Gift & Print Service API — Flask reference implementation.

In-memory only. Boots empty every process start (per-test-server isolation).
All structural names (headers, envelope fields, error ids, pagination params)
are taken verbatim from PRD.md / SCAFFOLD.yaml.
"""
import os
import re
import uuid
import string
import random
import threading
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (PRD §3.4 / §3.5 / §3.7)
# ---------------------------------------------------------------------------
FINISHES = {"MATTE", "GLOSSY", "LINEN", "LAY_FLAT", "METAL"}
PRODUCT_TYPES = {"PHOTOBOOK", "CARD", "CANVAS", "CALENDAR"}
SHIP_METHODS = {"STANDARD", "EXPRESS"}
PAYMENT_METHODS = {"CARD", "STORE_CREDIT"}
REFUND_DESTINATIONS = {"WALLET", "CARD"}
PROMO_KINDS = {"PERCENT", "FLAT", "FREE_SHIP"}
ROLES = {"Customer", "CatalogAdmin", "ProductionOperator"}

FINISH_SURCHARGE_CENTS = {"MATTE": 0, "GLOSSY": 300, "LINEN": 700, "LAY_FLAT": 1200, "METAL": 2500}
VOLUME_TIERS = [(1, Decimal("0.00")), (10, Decimal("0.05")), (25, Decimal("0.12")), (50, Decimal("0.20"))]
SHIPPING_CENTS = {"STANDARD": 799, "EXPRESS": 1999}
METHOD_TRANSIT_DAYS = {"STANDARD": 5, "EXPRESS": 2}
RESTOCK_PCT = Decimal("0.10")
PROMO_WINDOW_BUFFER_DAYS = 2
DEFAULT_DAILY_CAPACITY = 100000
DEFAULT_MIN_DPI = 150
DEFAULT_CLOCK_UTC = "2026-03-01T00:00:00Z"

PROMO_KIND_ORDER = {"PERCENT": 0, "FLAT": 1, "FREE_SHIP": 2}
ACTIVE_JOB_STATES = {"QUEUED", "PRINTING", "FINISHING"}

# ---------------------------------------------------------------------------
# In-memory store — empty at boot, never seeded
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.customers = {}
        self.addresses = {}
        self.templates = {}
        self.projects = {}
        self.photos = {}
        self.proofs = {}
        self.promotions = {}
        self.promo_windows = {}
        self.surge_windows = {}
        self.orders = {}
        self.jobs = {}
        self.shipments = {}
        self.clock = parse_dt(DEFAULT_CLOCK_UTC)
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


def parse_dt(s):
    if isinstance(s, datetime):
        dt = s
    else:
        v = s.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


db = Store()
LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_VALIDATION": 422,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_TEMPLATE_NOT_FOUND": 404,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_PROOF_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_ADDRESS_NOT_FOUND": 404,
    "ERR_PROMOTION_NOT_FOUND": 404,
    "ERR_PRODUCTION_JOB_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_SURGE_WINDOW_NOT_FOUND": 404,
    "ERR_TEMPLATE_RETIRED": 409,
    "ERR_INVALID_PROJECT_STATE": 409,
    "ERR_INSUFFICIENT_PHOTOS": 422,
    "ERR_TOO_MANY_PHOTOS": 422,
    "ERR_PHOTO_LOW_RESOLUTION": 422,
    "ERR_PROOF_NOT_PENDING": 409,
    "ERR_PROJECT_NOT_APPROVED": 409,
    "ERR_PROMO_NOT_STACKABLE": 409,
    "ERR_PROMO_NOT_ACTIVE": 409,
    "ERR_PROMO_LIMIT_EXCEEDED": 409,
    "ERR_PROMO_MIN_NOT_MET": 409,
    "ERR_ORDER_NOT_PAYABLE": 409,
    "ERR_INSUFFICIENT_STORE_CREDIT": 402,
    "ERR_SURGE_CAPACITY_FULL": 409,
    "ERR_ORDER_NOT_CANCELLABLE": 409,
    "ERR_PRODUCTION_NOT_COMPLETE": 409,
    "ERR_PRODUCTION_NOT_ADVANCEABLE": 409,
    "ERR_SHIPMENT_NOT_ADVANCEABLE": 409,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_STALE_PROJECT_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id.replace("ERR_", "").replace("_", " ").title()
        self.http_status = ERROR_HTTP.get(error_id, 400)


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _now_real():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(pagination=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": _now_real()}
    if pagination:
        m.update(pagination)
    return m


def _public(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def ok(data, status=200, pagination=None):
    rtype = "array" if isinstance(data, list) else "object"
    body = {"meta": _meta(pagination), "response_type": rtype,
            "data": [_public(d) for d in data] if isinstance(data, list) else _public(data)}
    return jsonify(body), status


@app.errorhandler(ApiError)
def _handle_api_error(err):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message}}
    return jsonify(body), err.http_status


@app.errorhandler(404)
def _not_found(_e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "Unknown route."}}
    return jsonify(body), 404


@app.errorhandler(405)
def _method_not_allowed(_e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed."}}
    return jsonify(body), 405


@app.before_request
def _acquire():
    LOCK.acquire()


@app.teardown_request
def _release(_exc):
    try:
        LOCK.release()
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# Timestamps / versioning
# ---------------------------------------------------------------------------
def fmt_ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_ts():
    return fmt_ts(db.clock)


def new_id():
    return str(uuid.uuid4())


def base_fields(common=True):
    now = clock_ts()
    rec = {"id": new_id(), "created_at": now, "_seq": db.next_seq()}
    if common:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(record):
    record["updated_at"] = clock_ts()
    record["version"] = record.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or malformed authentication headers.")
    g.user_id = uid
    g.role = role
    return uid, role


def authorize(*allowed_roles):
    authenticate()
    if g.role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role not permitted for this endpoint.")


def check_owner(owning_customer_id):
    if g.role == "Customer" and owning_customer_id != g.user_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", "Customer does not own this resource.")


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_or_404(coll, rid, error_id):
    rec = coll.get(rid)
    if rec is None:
        raise ApiError(error_id)
    return rec


# ---------------------------------------------------------------------------
# Body helpers
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require(b, field):
    if field not in b or b[field] is None:
        raise ApiError("ERR_VALIDATION", f"Missing required field: {field}")
    return b[field]


def require_str(b, field):
    v = require(b, field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", f"Field {field} must be a non-empty string.")
    return v


def require_int(b, field, minimum=None):
    v = require(b, field)
    if not is_int(v):
        raise ApiError("ERR_VALIDATION", f"Field {field} must be an integer.")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", f"Field {field} must be >= {minimum}.")
    return v


# ---------------------------------------------------------------------------
# Money / date math
# ---------------------------------------------------------------------------
def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def volume_tier_pct(quantity):
    pct = Decimal("0.00")
    for min_qty, tier_pct in VOLUME_TIERS:
        if quantity >= min_qty:
            pct = tier_pct
    return pct


def find_promo_by_code(code):
    for p in db.promotions.values():
        if p["code"] == code:
            return p
    return None


def promo_has_open_window(promo, instant):
    for w in db.promo_windows.values():
        if w["promotion_id"] != promo["id"]:
            continue
        if parse_dt(w["starts_at"]) <= instant <= parse_dt(w["ends_at"]):
            return True
    return False


def count_paid_redemptions(customer_id, code):
    n = 0
    for o in db.orders.values():
        if o["customer_id"] == customer_id and o["payment_status"] == "PAID" and code in (o.get("promo_codes") or []):
            n += 1
    return n


def covering_surge_window(instant, product_type):
    """Return the surge window covering `instant` (half-open) that applies to the
    given product_type (scope null or matching), or None."""
    for w in db.surge_windows.values():
        if parse_dt(w["starts_at"]) <= instant < parse_dt(w["ends_at"]):
            scope = w.get("product_type_scope")
            if scope is None or scope == product_type:
                return w
    return None


def resolve_and_gate_promos(codes, subtotal, product_type, placement, customer_id):
    """Apply promo eligibility gates in PRD priority order; return applicable promos."""
    codes = codes or []
    resolved = [p for p in (find_promo_by_code(c) for c in codes) if p is not None]

    # Priority 13: stackability (both quote and placement)
    if len(codes) > 1:
        for p in resolved:
            if not p["stackable"]:
                raise ApiError("ERR_PROMO_NOT_STACKABLE")

    applicable = [p for p in resolved
                  if p.get("product_type_scope") is None or p["product_type_scope"] == product_type]

    if placement:
        # Priority 14: promo window active
        for p in applicable:
            if not promo_has_open_window(p, db.clock):
                raise ApiError("ERR_PROMO_NOT_ACTIVE")
        # Priority 15: per-customer redemption limit
        for p in applicable:
            if count_paid_redemptions(customer_id, p["code"]) >= p["per_customer_limit"]:
                raise ApiError("ERR_PROMO_LIMIT_EXCEEDED")

    # Priority 16: minimum subtotal (both quote and placement)
    for p in applicable:
        if subtotal < p["min_subtotal_cents"]:
            raise ApiError("ERR_PROMO_MIN_NOT_MET")

    return applicable


def price_line(template, finish, quantity):
    unit = template["base_unit_price_cents"] + FINISH_SURCHARGE_CENTS[finish]
    pre = unit * quantity
    pct = volume_tier_pct(quantity)
    volume_discount = round_half_up(Decimal(pre) * pct)
    subtotal = pre - volume_discount
    return unit, subtotal


def promo_discount_and_shipping(applicable, subtotal, ship_method):
    ordered = sorted(applicable, key=lambda p: (PROMO_KIND_ORDER[p["kind"]], p["created_at"], p["_seq"]))
    total = 0
    free_ship = False
    for p in ordered:
        if p["kind"] == "PERCENT":
            raw = Decimal(subtotal) * Decimal(p["value"]) / Decimal(100)
        elif p["kind"] == "FLAT":
            raw = Decimal(p["value"])
        else:  # FREE_SHIP
            raw = Decimal(0)
            free_ship = True
        total += round_half_up(raw)
    discount = min(subtotal, total)
    shipping = 0 if free_ship else SHIPPING_CENTS[ship_method]
    return discount, shipping


def promised_ship_date(template, ship_method, surge_extra):
    base = db.clock.date()
    total_days = template["production_days"] + surge_extra + METHOD_TRANSIT_DAYS[ship_method]
    return (base + timedelta(days=total_days)).isoformat()


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(records):
    def _int_arg(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    limit = _int_arg("limit", 10)
    offset = _int_arg("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0

    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": (offset + len(page)) < total}
    return page, pagination


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authorize("CatalogAdmin")
    b = body()
    target = require_str(b, "to_iso8601")
    try:
        db.clock = parse_dt(target)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "Invalid to_iso8601 value.")
    return ok({"current_utc": fmt_ts(db.clock)}, 200)


# ===========================================================================
# Customers
# ===========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    authorize("CatalogAdmin")
    b = body()
    email = require_str(b, "email")
    full_name = require(b, "full_name")
    if not isinstance(full_name, str):
        raise ApiError("ERR_VALIDATION", "full_name must be a string.")
    rec = base_fields()
    rec.update({"email": email, "full_name": full_name, "store_credit_cents": 0})
    db.customers[rec["id"]] = rec
    return ok(rec, 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    authorize("Customer", "CatalogAdmin")
    cust = get_or_404(db.customers, cid, "ERR_CUSTOMER_NOT_FOUND")
    check_owner(cust["id"])
    return ok(cust, 200)


@app.route("/customers/<cid>/credit-adjustments", methods=["POST"])
def adjust_credit(cid):
    authorize("CatalogAdmin")
    cust = get_or_404(db.customers, cid, "ERR_CUSTOMER_NOT_FOUND")
    b = body()
    amount = require(b, "amount_cents")
    if not is_int(amount):
        raise ApiError("ERR_VALIDATION", "amount_cents must be an integer.")
    require_str(b, "reason")
    cust["store_credit_cents"] = max(0, cust["store_credit_cents"] + amount)
    touch(cust)
    return ok(cust, 200)


@app.route("/customers/<cid>/addresses", methods=["POST"])
def create_address(cid):
    authorize("Customer")
    cust = get_or_404(db.customers, cid, "ERR_CUSTOMER_NOT_FOUND")
    check_owner(cust["id"])
    b = body()
    rec = base_fields()
    is_first = not any(a["customer_id"] == cid for a in db.addresses.values())
    rec.update({
        "customer_id": cid,
        "recipient_name": require_str(b, "recipient_name"),
        "line1": require_str(b, "line1"),
        "line2": b.get("line2"),
        "city": require_str(b, "city"),
        "region": require_str(b, "region"),
        "postal_code": require_str(b, "postal_code"),
        "country": require_str(b, "country"),
        "is_default": is_first,
    })
    db.addresses[rec["id"]] = rec
    return ok(rec, 201)


@app.route("/customers/<cid>/addresses", methods=["GET"])
def list_addresses(cid):
    authorize("Customer", "CatalogAdmin")
    cust = get_or_404(db.customers, cid, "ERR_CUSTOMER_NOT_FOUND")
    check_owner(cust["id"])
    records = [a for a in db.addresses.values() if a["customer_id"] == cid]
    page, pagination = paginate(records)
    return ok(page, 200, pagination)


# ===========================================================================
# Templates
# ===========================================================================
@app.route("/templates", methods=["POST"])
def create_template():
    authorize("CatalogAdmin")
    b = body()
    product_type = require_str(b, "product_type")
    if product_type not in PRODUCT_TYPES:
        raise ApiError("ERR_VALIDATION", "Illegal product_type.")
    name = require_str(b, "name")
    surface_count = require_int(b, "surface_count", 1)
    base_price = require_int(b, "base_unit_price_cents", 0)
    production_days = require_int(b, "production_days", 0)
    allowed = require(b, "allowed_finishes")
    if not isinstance(allowed, list) or not allowed or any(f not in FINISHES for f in allowed):
        raise ApiError("ERR_VALIDATION", "allowed_finishes must be a non-empty subset of finishes.")
    min_photos = require_int(b, "min_photos", 1)
    max_photos = require_int(b, "max_photos", 1)
    if max_photos < min_photos:
        raise ApiError("ERR_VALIDATION", "max_photos must be >= min_photos.")
    min_dpi = b.get("min_dpi", DEFAULT_MIN_DPI)
    if min_dpi is None:
        min_dpi = DEFAULT_MIN_DPI
    if not is_int(min_dpi) or min_dpi < 1:
        raise ApiError("ERR_VALIDATION", "min_dpi must be an integer >= 1.")
    rec = base_fields()
    rec.update({
        "product_type": product_type, "name": name, "status": "ACTIVE",
        "surface_count": surface_count, "base_unit_price_cents": base_price,
        "production_days": production_days, "allowed_finishes": list(allowed),
        "min_photos": min_photos, "max_photos": max_photos, "min_dpi": min_dpi,
    })
    db.templates[rec["id"]] = rec
    return ok(rec, 201)


@app.route("/templates/<tid>", methods=["GET"])
def get_template(tid):
    authorize("Customer", "CatalogAdmin")
    tmpl = get_or_404(db.templates, tid, "ERR_TEMPLATE_NOT_FOUND")
    return ok(tmpl, 200)


@app.route("/templates/<tid>/retire", methods=["POST"])
def retire_template(tid):
    authorize("CatalogAdmin")
    tmpl = get_or_404(db.templates, tid, "ERR_TEMPLATE_NOT_FOUND")
    if tmpl["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_PROJECT_STATE", "Template is not ACTIVE.")
    tmpl["status"] = "RETIRED"
    touch(tmpl)
    return ok(tmpl, 200)


# ===========================================================================
# Projects
# ===========================================================================
@app.route("/projects", methods=["POST"])
def create_project():
    authorize("Customer")
    b = body()
    customer_id = require_str(b, "customer_id")
    template_id = require_str(b, "template_id")
    cust = get_or_404(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")
    tmpl = get_or_404(db.templates, template_id, "ERR_TEMPLATE_NOT_FOUND")
    check_owner(cust["id"])
    title = require_str(b, "title")
    if tmpl["status"] == "RETIRED":
        raise ApiError("ERR_TEMPLATE_RETIRED")
    rec = base_fields()
    rec.update({
        "customer_id": customer_id, "template_id": template_id, "title": title,
        "state": "DRAFT", "photo_count": 0, "placed_photo_count": 0, "current_proof_id": None,
    })
    db.projects[rec["id"]] = rec
    return ok(rec, 201)


@app.route("/projects/<pid>", methods=["GET"])
def get_project(pid):
    authorize("Customer", "CatalogAdmin")
    proj = get_or_404(db.projects, pid, "ERR_PROJECT_NOT_FOUND")
    check_owner(proj["customer_id"])
    return ok(proj, 200)


@app.route("/projects", methods=["GET"])
def list_projects():
    authorize("Customer", "CatalogAdmin")
    records = list(db.projects.values())
    cust_filter = request.args.get("customer_id")
    tmpl_filter = request.args.get("template_id")
    if cust_filter is not None:
        records = [p for p in records if p["customer_id"] == cust_filter]
    if tmpl_filter is not None:
        records = [p for p in records if p["template_id"] == tmpl_filter]
    if g.role == "Customer":
        records = [p for p in records if p["customer_id"] == g.user_id]
    page, pagination = paginate(records)
    return ok(page, 200, pagination)


@app.route("/projects/<pid>/photos", methods=["POST"])
def upload_photo(pid):
    authorize("Customer")
    proj = get_or_404(db.projects, pid, "ERR_PROJECT_NOT_FOUND")
    check_owner(proj["customer_id"])
    b = body()
    filename = require_str(b, "filename")
    width = require_int(b, "width_px", 1)
    height = require_int(b, "height_px", 1)
    dpi = require_int(b, "dpi", 1)
    rec = base_fields(common=False)
    rec.update({
        "project_id": pid, "filename": filename, "width_px": width,
        "height_px": height, "dpi": dpi, "status": "UPLOADED",
    })
    db.photos[rec["id"]] = rec
    proj["photo_count"] += 1
    touch(proj)
    return ok(rec, 201)


@app.route("/projects/<pid>/photos", methods=["GET"])
def list_photos(pid):
    authorize("Customer", "CatalogAdmin")
    proj = get_or_404(db.projects, pid, "ERR_PROJECT_NOT_FOUND")
    check_owner(proj["customer_id"])
    records = [p for p in db.photos.values() if p["project_id"] == pid]
    page, pagination = paginate(records)
    return ok(page, 200, pagination)


def project_photos(pid):
    return [p for p in db.photos.values() if p["project_id"] == pid]


@app.route("/projects/<pid>/autolayout", methods=["POST"])
def autolayout(pid):
    authorize("Customer")
    proj = get_or_404(db.projects, pid, "ERR_PROJECT_NOT_FOUND")
    check_owner(proj["customer_id"])
    tmpl = db.templates[proj["template_id"]]
    if proj["state"] != "DRAFT":
        raise ApiError("ERR_INVALID_PROJECT_STATE")
    photos = project_photos(pid)
    # Print-quality gate first (PRD 3.2).
    if any(p["dpi"] < tmpl["min_dpi"] for p in photos):
        raise ApiError("ERR_PHOTO_LOW_RESOLUTION")
    if proj["photo_count"] < tmpl["min_photos"]:
        raise ApiError("ERR_INSUFFICIENT_PHOTOS")
    if proj["photo_count"] > tmpl["max_photos"]:
        raise ApiError("ERR_TOO_MANY_PHOTOS")
    for p in photos:
        if p["status"] == "UPLOADED":
            p["status"] = "PLACED"
    proj["placed_photo_count"] = sum(1 for p in photos if p["status"] in ("PLACED", "LOCKED"))
    proj["state"] = "LAID_OUT"
    touch(proj)
    return ok(proj, 200)


@app.route("/projects/<pid>/proofs", methods=["POST"])
def generate_proof(pid):
    authorize("Customer")
    proj = get_or_404(db.projects, pid, "ERR_PROJECT_NOT_FOUND")
    check_owner(proj["customer_id"])
    b = body()
    expected = require_int(b, "expected_project_version")
    if proj["state"] not in ("LAID_OUT", "IN_PROOF"):
        raise ApiError("ERR_INVALID_PROJECT_STATE")
    if expected != proj["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION")
    # Supersede prior current proof.
    prior_id = proj.get("current_proof_id")
    if prior_id and prior_id in db.proofs:
        prior = db.proofs[prior_id]
        if prior["state"] == "GENERATED":
            prior["state"] = "SUPERSEDED"
            touch(prior)
    max_rev = max((pr["revision_number"] for pr in db.proofs.values() if pr["project_id"] == pid), default=0)
    rec = base_fields()
    rec.update({"project_id": pid, "revision_number": max_rev + 1, "state": "GENERATED"})
    db.proofs[rec["id"]] = rec
    proj["current_proof_id"] = rec["id"]
    proj["state"] = "IN_PROOF"
    touch(proj)
    return ok(rec, 201)


@app.route("/projects/<pid>/proofs", methods=["GET"])
def list_proofs(pid):
    authorize("Customer", "CatalogAdmin")
    proj = get_or_404(db.projects, pid, "ERR_PROJECT_NOT_FOUND")
    check_owner(proj["customer_id"])
    records = [p for p in db.proofs.values() if p["project_id"] == pid]
    page, pagination = paginate(records)
    return ok(page, 200, pagination)


@app.route("/proofs/<prid>/approve", methods=["POST"])
def approve_proof(prid):
    authorize("Customer")
    proof = get_or_404(db.proofs, prid, "ERR_PROOF_NOT_FOUND")
    proj = db.projects[proof["project_id"]]
    check_owner(proj["customer_id"])
    if proof["state"] != "GENERATED" or proj.get("current_proof_id") != proof["id"] or proj["state"] != "IN_PROOF":
        raise ApiError("ERR_PROOF_NOT_PENDING")
    # Cascade: proof -> project -> photos (depth 3).
    proof["state"] = "APPROVED"
    touch(proof)
    proj["state"] = "APPROVED"
    for p in project_photos(proj["id"]):
        if p["status"] == "PLACED":
            p["status"] = "LOCKED"
    proj["placed_photo_count"] = sum(1 for p in project_photos(proj["id"]) if p["status"] in ("PLACED", "LOCKED"))
    touch(proj)
    return ok(proof, 200)


@app.route("/proofs/<prid>/request-changes", methods=["POST"])
def request_changes(prid):
    authorize("Customer")
    proof = get_or_404(db.proofs, prid, "ERR_PROOF_NOT_FOUND")
    proj = db.projects[proof["project_id"]]
    check_owner(proj["customer_id"])
    body()  # optional note; not persisted as a field
    if proof["state"] != "GENERATED" or proj["state"] != "IN_PROOF":
        raise ApiError("ERR_PROOF_NOT_PENDING")
    proof["state"] = "CHANGES_REQUESTED"
    touch(proof)
    proj["state"] = "DRAFT"
    for p in project_photos(proj["id"]):
        if p["status"] == "PLACED":
            p["status"] = "UPLOADED"
    proj["placed_photo_count"] = sum(1 for p in project_photos(proj["id"]) if p["status"] in ("PLACED", "LOCKED"))
    touch(proj)
    return ok(proof, 200)


# ===========================================================================
# Pricing / Orders
# ===========================================================================
def validate_order_line(b, template, require_ship_method=True):
    quantity = require_int(b, "quantity", 1)
    finish = require_str(b, "finish")
    if finish not in FINISHES:
        raise ApiError("ERR_VALIDATION", "Illegal finish.")
    if finish not in template["allowed_finishes"]:
        raise ApiError("ERR_VALIDATION", "Finish not offered by this template.")
    ship_method = b.get("ship_method")
    if require_ship_method or ship_method is not None:
        if ship_method not in SHIP_METHODS:
            raise ApiError("ERR_VALIDATION", "Illegal ship_method.")
    return quantity, finish, ship_method


@app.route("/projects/<pid>/quote", methods=["POST"])
def quote_project(pid):
    authorize("Customer")
    proj = get_or_404(db.projects, pid, "ERR_PROJECT_NOT_FOUND")
    check_owner(proj["customer_id"])
    tmpl = db.templates[proj["template_id"]]
    b = body()
    quantity, finish, ship_method = validate_order_line(b, tmpl)
    ship_address_id = b.get("ship_address_id")
    if ship_address_id is not None:
        get_or_404(db.addresses, ship_address_id, "ERR_ADDRESS_NOT_FOUND")
    promo_codes = b.get("promo_codes") or []

    unit_price, subtotal = price_line(tmpl, finish, quantity)
    applicable = resolve_and_gate_promos(promo_codes, subtotal, tmpl["product_type"],
                                         placement=False, customer_id=proj["customer_id"])
    discount, shipping = promo_discount_and_shipping(applicable, subtotal, ship_method)
    total = max(0, subtotal - discount + shipping)
    psd = promised_ship_date(tmpl, ship_method, surge_extra=0)  # estimated variant
    return ok({
        "unit_price_cents": unit_price, "subtotal_cents": subtotal, "discount_cents": discount,
        "shipping_cents": shipping, "total_cents": total, "promised_ship_date": psd,
    }, 200)


@app.route("/orders", methods=["POST"])
def create_order():
    authorize("Customer")
    b = body()
    project_id = require_str(b, "project_id")
    proj = get_or_404(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    ship_address_id = require_str(b, "ship_address_id")
    addr = get_or_404(db.addresses, ship_address_id, "ERR_ADDRESS_NOT_FOUND")
    check_owner(proj["customer_id"])
    check_owner(addr["customer_id"])
    tmpl = db.templates[proj["template_id"]]
    quantity, finish, ship_method = validate_order_line(b, tmpl)
    payment_method = require_str(b, "payment_method")
    if payment_method not in PAYMENT_METHODS:
        raise ApiError("ERR_VALIDATION", "Illegal payment_method.")
    promo_codes = b.get("promo_codes") or []
    if not isinstance(promo_codes, list):
        raise ApiError("ERR_VALIDATION", "promo_codes must be an array.")

    # Cross-entity state guard (priority 7).
    if proj["state"] != "APPROVED":
        raise ApiError("ERR_PROJECT_NOT_APPROVED")

    unit_price, subtotal = price_line(tmpl, finish, quantity)
    applicable = resolve_and_gate_promos(promo_codes, subtotal, tmpl["product_type"],
                                         placement=True, customer_id=proj["customer_id"])
    discount, shipping = promo_discount_and_shipping(applicable, subtotal, ship_method)
    total = max(0, subtotal - discount + shipping)

    rec = base_fields()
    rec.update({
        "customer_id": proj["customer_id"], "project_id": project_id, "ship_address_id": ship_address_id,
        "reorder_of_id": None, "quantity": quantity, "finish": finish, "ship_method": ship_method,
        "payment_method": payment_method, "promo_codes": list(promo_codes),
        "unit_price_cents": unit_price, "subtotal_cents": subtotal, "discount_cents": discount,
        "shipping_cents": shipping, "total_cents": total, "paid_cents": 0, "refund_cents": 0,
        "refund_destination": None, "promised_ship_date": None,
        "payment_status": "UNPAID", "fulfillment_status": "NEW",
    })
    db.orders[rec["id"]] = rec
    return ok(rec, 201)


@app.route("/orders/<oid>", methods=["GET"])
def get_order(oid):
    authorize("Customer", "ProductionOperator", "CatalogAdmin")
    order = get_or_404(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    check_owner(order["customer_id"])
    return ok(order, 200)


@app.route("/orders", methods=["GET"])
def list_orders():
    authorize("Customer", "ProductionOperator", "CatalogAdmin")
    records = list(db.orders.values())
    for key, err in (("customer_id", None), ("project_id", None),
                     ("reorder_of_id", None), ("ship_address_id", None)):
        val = request.args.get(key)
        if val is not None:
            records = [o for o in records if o.get(key) == val]
    if g.role == "Customer":
        records = [o for o in records if o["customer_id"] == g.user_id]
    page, pagination = paginate(records)
    return ok(page, 200, pagination)


@app.route("/orders/<oid>/pay", methods=["POST"])
def pay_order(oid):
    authorize("Customer")
    order = get_or_404(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    check_owner(order["customer_id"])
    if order["payment_status"] != "UNPAID" or order["fulfillment_status"] != "NEW":
        raise ApiError("ERR_ORDER_NOT_PAYABLE")
    proj = db.projects[order["project_id"]]
    tmpl = db.templates[proj["template_id"]]
    product_type = tmpl["product_type"]

    scheduled_dt = db.clock
    scheduled_date = scheduled_dt.date().isoformat()
    window = covering_surge_window(scheduled_dt, product_type)

    # Priority 17: surge capacity admission.
    if window is not None:
        scope = window.get("product_type_scope")
        used = 0
        for job in db.jobs.values():
            if job["scheduled_date"] != scheduled_date or job["state"] not in ACTIVE_JOB_STATES:
                continue
            job_order = db.orders.get(job["order_id"])
            if job_order is None:
                continue
            job_pt = db.templates[db.projects[job_order["project_id"]]["template_id"]]["product_type"]
            if scope is None or job_pt == scope:
                used += job["quantity"]
        remaining = window["capacity_per_day"] - used
        if order["quantity"] > remaining:
            raise ApiError("ERR_SURGE_CAPACITY_FULL")

    # Priority 18: store-credit sufficiency.
    cust = db.customers[order["customer_id"]]
    if order["payment_method"] == "STORE_CREDIT" and cust["store_credit_cents"] < order["total_cents"]:
        raise ApiError("ERR_INSUFFICIENT_STORE_CREDIT")

    # Apply payment.
    order["payment_status"] = "PAID"
    order["paid_cents"] = order["total_cents"]
    if order["payment_method"] == "STORE_CREDIT":
        cust["store_credit_cents"] -= order["total_cents"]
        touch(cust)
    order["fulfillment_status"] = "IN_PRODUCTION"

    surge_extra = window["turnaround_extra_days"] if window is not None else 0
    order["promised_ship_date"] = promised_ship_date(tmpl, order["ship_method"], surge_extra)

    job = base_fields()
    job.update({
        "order_id": order["id"], "quantity": order["quantity"], "scheduled_date": scheduled_date,
        "surge_window_id": window["id"] if window is not None else None, "state": "QUEUED",
    })
    db.jobs[job["id"]] = job

    touch(order)
    return ok(order, 200)


@app.route("/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    authorize("Customer")
    order = get_or_404(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    check_owner(order["customer_id"])
    b = body()
    refund_destination = require_str(b, "refund_destination")
    if refund_destination not in REFUND_DESTINATIONS:
        raise ApiError("ERR_VALIDATION", "Illegal refund_destination.")
    if order["fulfillment_status"] not in ("NEW", "IN_PRODUCTION"):
        raise ApiError("ERR_ORDER_NOT_CANCELLABLE")

    was_paid = order["payment_status"] == "PAID"

    # Fulfillment cascade: order -> production job(s) -> shipment(s).
    order["fulfillment_status"] = "CANCELLED"
    for job in db.jobs.values():
        if job["order_id"] == oid and job["state"] != "CANCELLED":
            job["state"] = "CANCELLED"  # releases capacity (excluded from active sum)
            touch(job)
    for ship in db.shipments.values():
        if ship["order_id"] == oid and ship["state"] in ("LABEL_CREATED", "IN_TRANSIT"):
            ship["state"] = "VOID"
            touch(ship)

    # Money settlement (only if the order had been paid).
    if was_paid:
        order["payment_status"] = "REFUNDED"
        order["refund_destination"] = refund_destination
        captured = order["paid_cents"]
        if refund_destination == "WALLET":
            refund = captured
            cust = db.customers[order["customer_id"]]
            cust["store_credit_cents"] += refund
            touch(cust)
        else:  # CARD
            restock = round_half_up(Decimal(order["subtotal_cents"]) * RESTOCK_PCT)
            refund = max(0, captured - restock)
        order["refund_cents"] = refund

    touch(order)
    return ok(order, 200)


@app.route("/orders/<oid>/reorder", methods=["POST"])
def reorder(oid):
    authorize("Customer")
    src = get_or_404(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    check_owner(src["customer_id"])
    b = body()
    ship_address_id = b.get("ship_address_id") or src["ship_address_id"]
    addr = get_or_404(db.addresses, ship_address_id, "ERR_ADDRESS_NOT_FOUND")
    check_owner(addr["customer_id"])
    ship_method = b.get("ship_method") or src["ship_method"]
    if ship_method not in SHIP_METHODS:
        raise ApiError("ERR_VALIDATION", "Illegal ship_method.")

    proj = db.projects[src["project_id"]]
    tmpl = db.templates[proj["template_id"]]
    quantity = src["quantity"]
    finish = src["finish"]

    unit_price, subtotal = price_line(tmpl, finish, quantity)
    discount, shipping = promo_discount_and_shipping([], subtotal, ship_method)
    total = max(0, subtotal - discount + shipping)

    rec = base_fields()
    rec.update({
        "customer_id": src["customer_id"], "project_id": src["project_id"], "ship_address_id": ship_address_id,
        "reorder_of_id": src["id"], "quantity": quantity, "finish": finish, "ship_method": ship_method,
        "payment_method": src["payment_method"], "promo_codes": [],
        "unit_price_cents": unit_price, "subtotal_cents": subtotal, "discount_cents": discount,
        "shipping_cents": shipping, "total_cents": total, "paid_cents": 0, "refund_cents": 0,
        "refund_destination": None, "promised_ship_date": None,
        "payment_status": "UNPAID", "fulfillment_status": "NEW",
    })
    db.orders[rec["id"]] = rec
    return ok(rec, 201)


# ===========================================================================
# Production & Shipping
# ===========================================================================
@app.route("/orders/<oid>/production-job", methods=["GET"])
def list_production_jobs(oid):
    authorize("Customer", "ProductionOperator", "CatalogAdmin")
    order = get_or_404(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    check_owner(order["customer_id"])
    records = [j for j in db.jobs.values() if j["order_id"] == oid]
    page, pagination = paginate(records)
    return ok(page, 200, pagination)


@app.route("/production-jobs/<jid>/advance", methods=["POST"])
def advance_job(jid):
    authorize("ProductionOperator")
    job = get_or_404(db.jobs, jid, "ERR_PRODUCTION_JOB_NOT_FOUND")
    nxt = {"QUEUED": "PRINTING", "PRINTING": "FINISHING", "FINISHING": "DONE"}.get(job["state"])
    if nxt is None:
        raise ApiError("ERR_PRODUCTION_NOT_ADVANCEABLE")
    job["state"] = nxt
    touch(job)
    return ok(job, 200)


@app.route("/orders/<oid>/shipments", methods=["POST"])
def create_shipment(oid):
    authorize("ProductionOperator")
    order = get_or_404(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    b = body()
    address_id = require_str(b, "address_id")
    addr = get_or_404(db.addresses, address_id, "ERR_ADDRESS_NOT_FOUND")
    carrier = require_str(b, "carrier")
    method = require_str(b, "method")
    if method not in SHIP_METHODS:
        raise ApiError("ERR_VALIDATION", "Illegal shipment method.")
    # Cross-entity state guard (priority 8): the order's production job must be DONE.
    jobs = [j for j in db.jobs.values() if j["order_id"] == oid]
    if not any(j["state"] == "DONE" for j in jobs):
        raise ApiError("ERR_PRODUCTION_NOT_COMPLETE")
    rec = base_fields()
    rec.update({
        "order_id": oid, "address_id": address_id, "carrier": carrier, "method": method,
        "tracking_code": "TRK" + uuid.uuid4().hex[:16].upper(), "state": "LABEL_CREATED",
    })
    db.shipments[rec["id"]] = rec
    return ok(rec, 201)


@app.route("/shipments/<sid>", methods=["GET"])
def get_shipment(sid):
    authorize("Customer", "ProductionOperator", "CatalogAdmin")
    ship = get_or_404(db.shipments, sid, "ERR_SHIPMENT_NOT_FOUND")
    if g.role == "Customer":
        order = db.orders.get(ship["order_id"])
        if order is not None:
            check_owner(order["customer_id"])
    return ok(ship, 200)


@app.route("/shipments", methods=["GET"])
def list_shipments():
    authorize("Customer", "ProductionOperator", "CatalogAdmin")
    records = list(db.shipments.values())
    order_filter = request.args.get("order_id")
    address_filter = request.args.get("address_id")
    if order_filter is not None:
        records = [s for s in records if s["order_id"] == order_filter]
    if address_filter is not None:
        records = [s for s in records if s["address_id"] == address_filter]
    if g.role == "Customer":
        owned = {o["id"] for o in db.orders.values() if o["customer_id"] == g.user_id}
        records = [s for s in records if s["order_id"] in owned]
    page, pagination = paginate(records)
    return ok(page, 200, pagination)


@app.route("/shipments/<sid>/advance", methods=["POST"])
def advance_shipment(sid):
    authorize("ProductionOperator")
    ship = get_or_404(db.shipments, sid, "ERR_SHIPMENT_NOT_FOUND")
    order = db.orders.get(ship["order_id"])
    if ship["state"] == "LABEL_CREATED":
        ship["state"] = "IN_TRANSIT"
        if order is not None:
            order["fulfillment_status"] = "SHIPPED"
            touch(order)
    elif ship["state"] == "IN_TRANSIT":
        ship["state"] = "DELIVERED"
        if order is not None:
            order["fulfillment_status"] = "DELIVERED"
            touch(order)
    else:
        raise ApiError("ERR_SHIPMENT_NOT_ADVANCEABLE")
    touch(ship)
    return ok(ship, 200)


# ===========================================================================
# Promotions
# ===========================================================================
@app.route("/promotions", methods=["POST"])
def create_promotion():
    authorize("CatalogAdmin")
    b = body()
    code = require_str(b, "code")
    kind = require_str(b, "kind")
    if kind not in PROMO_KINDS:
        raise ApiError("ERR_VALIDATION", "Illegal promotion kind.")
    value = b.get("value", 0)
    if value is None:
        value = 0
    if not is_int(value) or value < 0:
        raise ApiError("ERR_VALIDATION", "value must be an integer >= 0.")
    min_subtotal = b.get("min_subtotal_cents", 0)
    if min_subtotal is None:
        min_subtotal = 0
    if not is_int(min_subtotal) or min_subtotal < 0:
        raise ApiError("ERR_VALIDATION", "min_subtotal_cents must be an integer >= 0.")
    stackable = b.get("stackable", False)
    if stackable is None:
        stackable = False
    if not isinstance(stackable, bool):
        raise ApiError("ERR_VALIDATION", "stackable must be a boolean.")
    per_customer_limit = b.get("per_customer_limit", 1)
    if per_customer_limit is None:
        per_customer_limit = 1
    if not is_int(per_customer_limit) or per_customer_limit < 1:
        raise ApiError("ERR_VALIDATION", "per_customer_limit must be an integer >= 1.")
    scope = b.get("product_type_scope")
    if scope is not None and scope not in PRODUCT_TYPES:
        raise ApiError("ERR_VALIDATION", "Illegal product_type_scope.")
    rec = base_fields()
    rec.update({
        "code": code, "kind": kind, "value": value, "min_subtotal_cents": min_subtotal,
        "stackable": stackable, "per_customer_limit": per_customer_limit, "product_type_scope": scope,
    })
    db.promotions[rec["id"]] = rec
    return ok(rec, 201)


@app.route("/promotions/<pmid>", methods=["GET"])
def get_promotion(pmid):
    authorize("Customer", "CatalogAdmin")
    promo = get_or_404(db.promotions, pmid, "ERR_PROMOTION_NOT_FOUND")
    return ok(promo, 200)


@app.route("/promotions/<pmid>/windows", methods=["POST"])
def create_promo_window(pmid):
    authorize("CatalogAdmin")
    promo = get_or_404(db.promotions, pmid, "ERR_PROMOTION_NOT_FOUND")
    b = body()
    starts_raw = require_str(b, "starts_at")
    ends_raw = require_str(b, "ends_at")
    try:
        starts = parse_dt(starts_raw)
        ends = parse_dt(ends_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "Invalid window timestamps.")
    if not (ends > starts):
        raise ApiError("ERR_VALIDATION", "ends_at must be strictly after starts_at.")
    buffer = timedelta(days=PROMO_WINDOW_BUFFER_DAYS)
    for w in db.promo_windows.values():
        if w["promotion_id"] != pmid:
            continue
        e_start = parse_dt(w["starts_at"])
        e_end = parse_dt(w["ends_at"])
        # Accept only when separated by >= buffer on one side (closed intervals).
        if (starts - e_end >= buffer) or (e_start - ends >= buffer):
            continue
        raise ApiError("ERR_WINDOW_OVERLAP")
    rec = base_fields()
    rec.update({"promotion_id": pmid, "starts_at": starts_raw, "ends_at": ends_raw})
    db.promo_windows[rec["id"]] = rec
    return ok(rec, 201)


@app.route("/promotions/<pmid>/windows", methods=["GET"])
def list_promo_windows(pmid):
    authorize("CatalogAdmin")
    promo = get_or_404(db.promotions, pmid, "ERR_PROMOTION_NOT_FOUND")
    records = [w for w in db.promo_windows.values() if w["promotion_id"] == pmid]
    page, pagination = paginate(records)
    return ok(page, 200, pagination)


# ===========================================================================
# Surge windows
# ===========================================================================
@app.route("/surge-windows", methods=["POST"])
def create_surge_window():
    authorize("CatalogAdmin")
    b = body()
    name = require_str(b, "name")
    starts_raw = require_str(b, "starts_at")
    ends_raw = require_str(b, "ends_at")
    try:
        starts = parse_dt(starts_raw)
        ends = parse_dt(ends_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "Invalid window timestamps.")
    if not (ends > starts):
        raise ApiError("ERR_VALIDATION", "ends_at must be strictly after starts_at.")
    extra = require_int(b, "turnaround_extra_days", 0)
    capacity = require_int(b, "capacity_per_day", 1)
    scope = b.get("product_type_scope")
    if scope is not None and scope not in PRODUCT_TYPES:
        raise ApiError("ERR_VALIDATION", "Illegal product_type_scope.")
    # Half-open intervals: touching endpoints allowed, interiors may not overlap.
    for w in db.surge_windows.values():
        e_start = parse_dt(w["starts_at"])
        e_end = parse_dt(w["ends_at"])
        if starts < e_end and e_start < ends:
            raise ApiError("ERR_WINDOW_OVERLAP")
    rec = base_fields()
    rec.update({
        "name": name, "starts_at": starts_raw, "ends_at": ends_raw,
        "turnaround_extra_days": extra, "capacity_per_day": capacity, "product_type_scope": scope,
    })
    db.surge_windows[rec["id"]] = rec
    return ok(rec, 201)


@app.route("/surge-windows/<swid>", methods=["GET"])
def get_surge_window(swid):
    authorize("CatalogAdmin", "ProductionOperator")
    w = get_or_404(db.surge_windows, swid, "ERR_SURGE_WINDOW_NOT_FOUND")
    return ok(w, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
