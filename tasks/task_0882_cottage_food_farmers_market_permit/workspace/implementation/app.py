"""Cottage-Food & Farmers-Market Vendor Permit API — Python/Flask reference implementation.

In-memory only. Fresh boot wipes all state; no entity is seeded at startup.
All server time comes from a logical clock (default 2026-05-01T00:00:00Z).
"""
import os
import re
import uuid
import random
import string
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)
app.url_map.strict_slashes = False

# Serialize all requests to keep cascades / OCC / capacity deterministic under
# the framework's concurrent race tests (ThreadPoolExecutor).
_LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# Constants (PRD §2.5, §3.3, §3.5, §3.7, §3.8)
# ---------------------------------------------------------------------------
PERMIT_TERM_DAYS = 365
ANNUAL_CAP_CENTS = {"CLASS_A": 7_500_000, "CLASS_B": 15_000_000}
BASE_FEE_BY_CLASS = {"CLASS_A": 2_500, "CLASS_B": 7_500}
INSPECTION_SURCHARGE = 3_000
MARKET_FEE_RATE = Decimal("0.06")
SAMPLING_EXEMPTION_CENTS = 50_000
PROJECTED_UNITS_BY_SEVERITY = {"LOW": 10, "MEDIUM": 50, "HIGH": 200}
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

ROLES = {"Producer", "HealthInspector", "MarketManager", "HealthAdmin"}

FOOD_CATEGORIES = {
    "BAKED_GOODS", "JAMS_JELLIES", "DRY_MIXES", "CANDY", "ACID_PICKLES",
    "FERMENTED_VEG", "DAIRY", "MEAT_POULTRY", "LOW_ACID_CANNED", "JUICE",
}
WATER_SOURCES = {"PUBLIC", "PRIVATE_WELL"}
PERMIT_CLASSES = {"CLASS_A", "CLASS_B"}
INSPECTION_TYPES = {"ROUTINE", "RENEWAL", "COMPLAINT"}
COMPLAINT_CATEGORIES = {"LABELING", "ILLNESS", "UNAPPROVED_FOOD", "SALES_VENUE"}
VENUE_TYPES = {"CERTIFIED_FM", "TEMP_EVENT", "ONLINE"}
RECALL_REASONS = {"ILLNESS_OUTBREAK", "MISLABEL", "CONTAMINATION"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH"}

MANIFEST_NON_TERMINAL = {"SUBMITTED", "APPROVED", "CHECKED_IN"}
MANIFEST_OCCUPYING = {"APPROVED", "CHECKED_IN"}

EVENT_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
DB = {
    "producers": {}, "policies": {}, "products": {}, "permits": {},
    "inspections": {}, "complaints": {}, "markets": {}, "manifests": {},
    "sales": {}, "recalls": {},
}
_SEQ = {"n": 0}
_CLOCK = {"dt": None}


def _reset_clock():
    _CLOCK["dt"] = parse_iso(DEFAULT_CLOCK_ISO)


# ---------------------------------------------------------------------------
# Clock / time helpers
# ---------------------------------------------------------------------------
def parse_iso(s):
    """Parse an ISO-8601 instant (with trailing Z or offset) into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("bad iso")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def render_iso(dt):
    """Render an aware datetime as ISO-8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def now_dt():
    return _CLOCK["dt"]


def now_iso():
    return render_iso(_CLOCK["dt"])


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_id():
    return str(uuid.uuid4())


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def mint_token():
    return "vt_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


# ---------------------------------------------------------------------------
# Errors + envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def meta_base(pagination=None):
    m = {"api_request_id": gen_request_id(), "api_request_timestamp": now_iso()}
    if pagination:
        m.update(pagination)
    return m


def ok(data, status=200, pagination=None):
    rtype = "array" if isinstance(data, list) else "object"
    body = {"meta": meta_base(pagination), "response_type": rtype, "data": data}
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    body = {"meta": meta_base(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "route not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(_e):
    body = {"meta": meta_base(), "response_type": "error",
            "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "method not allowed"}}
    return jsonify(body), 405


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = {"meta": meta_base(), "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(e)}}
    return jsonify(body), 500


# Serialize every request (deterministic cascades/OCC).
@app.before_request
def _acquire():
    _LOCK.acquire()
    g._locked = True


@app.teardown_request
def _release(_exc):
    if getattr(g, "_locked", False):
        try:
            _LOCK.release()
        except RuntimeError:
            pass
        g._locked = False


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_AUTH_CONTEXT", 400, "Missing or unknown auth context")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Body parsing / validation helpers
# ---------------------------------------------------------------------------
def get_body():
    if request.method in ("GET", "DELETE"):
        return {}
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Body must be a JSON object")
    return body


def inv(msg="Invalid request"):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def req_str(body, key, allow_empty=False):
    if key not in body or body[key] is None:
        inv(f"Missing required field: {key}")
    v = body[key]
    if not isinstance(v, str):
        inv(f"Field {key} must be a string")
    if not allow_empty and v == "":
        inv(f"Field {key} must not be empty")
    return v


def req_enum(body, key, allowed):
    v = req_str(body, key, allow_empty=True)
    if v not in allowed:
        inv(f"Field {key} has an illegal value")
    return v


def req_bool(body, key):
    if key not in body or body[key] is None:
        inv(f"Missing required field: {key}")
    v = body[key]
    if not isinstance(v, bool):
        inv(f"Field {key} must be a boolean")
    return v


def req_int(body, key, min_value=None, strict_min=None):
    if key not in body or body[key] is None:
        inv(f"Missing required field: {key}")
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        inv(f"Field {key} must be an integer")
    if min_value is not None and v < min_value:
        inv(f"Field {key} out of range")
    if strict_min is not None and v <= strict_min:
        inv(f"Field {key} must be greater than {strict_min}")
    return v


def opt_number(body, key):
    if key not in body or body[key] is None:
        return None
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        inv(f"Field {key} must be a number")
    return v


def opt_str(body, key):
    if key not in body or body[key] is None:
        return None
    v = body[key]
    if not isinstance(v, str):
        inv(f"Field {key} must be a string")
    return v


def parse_pagination():
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items):
    """items: list of raw entity dicts (already filtered). Sort + slice."""
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    has_more = offset + limit < total
    pagination = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return page, pagination


# ---------------------------------------------------------------------------
# Entity lookups
# ---------------------------------------------------------------------------
def _find(coll, eid, err):
    if not isinstance(eid, str) or eid not in DB[coll]:
        raise ApiError(err, 404, f"{err}")
    return DB[coll][eid]


def get_producer(pid):
    return _find("producers", pid, "ERR_PRODUCER_NOT_FOUND")


def get_product(pid):
    return _find("products", pid, "ERR_PRODUCT_NOT_FOUND")


def get_permit(pid):
    return _find("permits", pid, "ERR_PERMIT_NOT_FOUND")


def get_inspection(iid):
    return _find("inspections", iid, "ERR_INSPECTION_NOT_FOUND")


def get_complaint(cid):
    return _find("complaints", cid, "ERR_COMPLAINT_NOT_FOUND")


def get_market(mid):
    return _find("markets", mid, "ERR_MARKET_NOT_FOUND")


def get_manifest(mid):
    return _find("manifests", mid, "ERR_MANIFEST_NOT_FOUND")


def get_sale(sid):
    return _find("sales", sid, "ERR_SALES_RECORD_NOT_FOUND")


def get_recall(rid):
    return _find("recalls", rid, "ERR_RECALL_NOT_FOUND")


# ---------------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------------
def base_common(with_version=True):
    ts = now_iso()
    d = {"id": new_id(), "created_at": ts, "_seq": next_seq()}
    if with_version:
        d["updated_at"] = ts
        d["version"] = 1
    return d


def bump(entity):
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def producer_issued_permits(producer_id):
    return [p for p in DB["permits"].values()
            if p["producer_id"] == producer_id and p["status"] == "ISSUED"]


def market_day_occupancy(market_id, event_date):
    return sum(1 for m in DB["manifests"].values()
               if m["market_id"] == market_id and m["event_date"] == event_date
               and m["status"] in MANIFEST_OCCUPYING)


def void_manifest_system(manifest):
    """System void of a non-terminal manifest; free slot if it was occupying."""
    was_occupying = manifest["status"] in MANIFEST_OCCUPYING
    manifest["status"] = "VOIDED"
    bump(manifest)
    if was_occupying:
        market = DB["markets"].get(manifest["market_id"])
        if market:
            bump(market)  # release day-slot


def suspend_producer_cascade(producer):
    """Cap-breach / recall suspension cascade (PRD §2.8)."""
    producer["status"] = "SUSPENDED"
    bump(producer)
    # Suspend the producer's ISSUED permits.
    for permit in producer_issued_permits(producer["id"]):
        permit["status"] = "SUSPENDED"
        bump(permit)
    # Void every non-terminal manifest belonging to this producer.
    for manifest in DB["manifests"].values():
        if manifest["producer_id"] == producer["id"] and manifest["status"] in MANIFEST_NON_TERMINAL:
            void_manifest_system(manifest)


def revoke_permit_cascade(permit):
    """Revocation cascade: void non-terminal manifests bound to this permit."""
    for manifest in DB["manifests"].values():
        if manifest["permit_id"] == permit["id"] and manifest["status"] in MANIFEST_NON_TERMINAL:
            void_manifest_system(manifest)


def recompute_booth_fee(manifest):
    total = 0
    for sr in DB["sales"].values():
        if sr["manifest_id"] == manifest["id"] and sr["status"] == "RECORDED":
            line = (Decimal(sr["gross_amount_cents"]) * MARKET_FEE_RATE).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP)
            total += int(line)
    manifest["booth_fee_cents"] = total  # computed rollup: not a version-bumping mutation


def recompute_ytd(producer):
    total = 0
    for sr in DB["sales"].values():
        if sr["producer_id"] == producer["id"] and sr["status"] == "RECORDED":
            total += sr["gross_amount_cents"]
    producer["ytd_gross_sales_cents"] = total  # computed ledger rollup


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def s_producer(p):
    return {
        "id": p["id"], "business_name": p["business_name"], "operator_name": p["operator_name"],
        "contact_email": p["contact_email"], "county": p["county"], "water_source": p["water_source"],
        "status": p["status"], "verification_token": p["verification_token"],
        "verified_at": p["verified_at"], "ytd_gross_sales_cents": p["ytd_gross_sales_cents"],
        "created_at": p["created_at"], "updated_at": p["updated_at"], "version": p["version"],
    }


def s_policy(p):
    return {
        "id": p["id"], "food_category": p["food_category"],
        "is_cottage_allowed": p["is_cottage_allowed"], "max_ph": p["max_ph"],
        "max_water_activity": p["max_water_activity"], "class_b_required": p["class_b_required"],
        "requires_allergen_label": p["requires_allergen_label"], "created_at": p["created_at"],
    }


def s_product(p):
    return {
        "id": p["id"], "producer_id": p["producer_id"], "name": p["name"],
        "food_category": p["food_category"], "requires_refrigeration": p["requires_refrigeration"],
        "ph_value": p["ph_value"], "water_activity": p["water_activity"],
        "unit_price_cents": p["unit_price_cents"], "compliance_status": p["compliance_status"],
        "label_status": p["label_status"], "reject_reason": p["reject_reason"],
        "created_at": p["created_at"], "updated_at": p["updated_at"], "version": p["version"],
    }


def s_permit(p):
    is_expired = bool(p["expires_at"]) and now_dt() > parse_iso(p["expires_at"])
    return {
        "id": p["id"], "producer_id": p["producer_id"], "permit_class": p["permit_class"],
        "status": p["status"], "inspection_required": p["inspection_required"],
        "annual_cap_cents": p["annual_cap_cents"], "fee_cents": p["fee_cents"],
        "term_start": p["term_start"], "expires_at": p["expires_at"],
        "renewal_count": p["renewal_count"], "is_expired": is_expired,
        "created_at": p["created_at"], "updated_at": p["updated_at"], "version": p["version"],
    }


def s_inspection(i):
    return {
        "id": i["id"], "permit_id": i["permit_id"], "inspection_type": i["inspection_type"],
        "status": i["status"], "scheduled_for": i["scheduled_for"],
        "violation_count": i["violation_count"], "inspector_user_id": i["inspector_user_id"],
        "created_at": i["created_at"], "updated_at": i["updated_at"], "version": i["version"],
    }


def s_complaint(c):
    return {
        "id": c["id"], "producer_id": c["producer_id"], "product_id": c["product_id"],
        "category": c["category"], "description": c["description"], "status": c["status"],
        "filed_by_user_id": c["filed_by_user_id"], "reviewed_by_user_id": c["reviewed_by_user_id"],
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def s_market(m):
    return {
        "id": m["id"], "name": m["name"], "county": m["county"], "venue_type": m["venue_type"],
        "max_vendors_per_day": m["max_vendors_per_day"], "allowed_classes": m["allowed_classes"],
        "status": m["status"], "created_at": m["created_at"], "updated_at": m["updated_at"],
        "version": m["version"],
    }


def s_manifest(m):
    return {
        "id": m["id"], "producer_id": m["producer_id"], "market_id": m["market_id"],
        "permit_id": m["permit_id"], "event_date": m["event_date"], "product_ids": m["product_ids"],
        "status": m["status"], "booth_fee_cents": m["booth_fee_cents"],
        "created_at": m["created_at"], "updated_at": m["updated_at"], "version": m["version"],
    }


def s_sale(s):
    return {
        "id": s["id"], "manifest_id": s["manifest_id"], "producer_id": s["producer_id"],
        "gross_amount_cents": s["gross_amount_cents"], "status": s["status"],
        "recorded_at": s["recorded_at"], "created_at": s["created_at"],
        "updated_at": s["updated_at"], "version": s["version"],
    }


def s_recall(r):
    return {
        "id": r["id"], "producer_id": r["producer_id"], "product_id": r["product_id"],
        "reason": r["reason"], "severity": r["severity"], "status": r["status"],
        "recalled_units": r["recalled_units"],
        "estimated_liability_cents": r["estimated_liability_cents"],
        "final_liability_cents": r["final_liability_cents"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


# ===========================================================================
# Producer endpoints
# ===========================================================================
@app.route("/cottage-food/producers", methods=["POST"])
def create_producer():
    _uid, role = authenticate()
    authorize(role, {"Producer", "HealthAdmin"})
    body = get_body()
    business_name = req_str(body, "business_name")
    operator_name = req_str(body, "operator_name")
    contact_email = req_str(body, "contact_email")
    county = req_str(body, "county")
    water_source = req_enum(body, "water_source", WATER_SOURCES)
    p = base_common()
    p.update({
        "business_name": business_name, "operator_name": operator_name,
        "contact_email": contact_email, "county": county, "water_source": water_source,
        "status": "PENDING_VERIFICATION", "verification_token": mint_token(),
        "verified_at": None, "ytd_gross_sales_cents": 0,
    })
    DB["producers"][p["id"]] = p
    return ok(s_producer(p), 201)


@app.route("/cottage-food/producers", methods=["GET"])
def list_producers():
    _uid, role = authenticate()
    authorize(role, {"Producer", "HealthInspector", "HealthAdmin", "MarketManager"})
    county = request.args.get("county")
    status = request.args.get("status")
    items = [p for p in DB["producers"].values()
             if (county is None or p["county"] == county)
             and (status is None or p["status"] == status)]
    page, pg = paginate(items)
    return ok([s_producer(p) for p in page], 200, pg)


@app.route("/cottage-food/producers/<pid>", methods=["GET"])
def read_producer(pid):
    _uid, role = authenticate()
    authorize(role, {"Producer", "HealthInspector", "HealthAdmin", "MarketManager"})
    return ok(s_producer(get_producer(pid)), 200)


@app.route("/cottage-food/producers/<pid>/verify", methods=["POST"])
def verify_producer(pid):
    uid, role = authenticate()
    authorize(role, {"Producer"})
    producer = get_producer(pid)
    if uid != producer["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Producers may only verify their own registration")
    body = get_body()
    token = req_str(body, "verification_token", allow_empty=True)
    if producer["status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_INVALID_REQUEST", 400, "Producer is not pending verification")
    if token != producer["verification_token"]:
        raise ApiError("ERR_INVALID_REQUEST", 400, "verification_token does not match")
    producer["status"] = "REGISTERED"
    producer["verified_at"] = now_iso()
    bump(producer)
    return ok(s_producer(producer), 200)


@app.route("/cottage-food/producers/<pid>/reinstate", methods=["POST"])
def reinstate_producer(pid):
    _uid, role = authenticate()
    authorize(role, {"HealthAdmin"})
    producer = get_producer(pid)
    # Blocked while any recall for this producer is still INITIATED.
    for r in DB["recalls"].values():
        if r["producer_id"] == producer["id"] and r["status"] == "INITIATED":
            raise ApiError("ERR_RECALL_INVALID_STATE", 409, "Recall still in progress")
    if producer["status"] != "SUSPENDED":
        raise ApiError("ERR_RECALL_INVALID_STATE", 409, "Producer is not suspended")
    producer["status"] = "REGISTERED"
    bump(producer)
    return ok(s_producer(producer), 200)


@app.route("/cottage-food/producers/<pid>/compliance-summary", methods=["GET"])
def compliance_summary(pid):
    _uid, role = authenticate()
    authorize(role, {"Producer", "HealthInspector", "HealthAdmin"})
    producer = get_producer(pid)
    provisional = 0
    audited = 0
    for sr in DB["sales"].values():
        if sr["producer_id"] == producer["id"] and sr["status"] == "RECORDED":
            provisional += sr["gross_amount_cents"]
            manifest = DB["manifests"].get(sr["manifest_id"])
            if manifest and manifest["status"] == "CHECKED_IN":
                audited += sr["gross_amount_cents"]
    audited = max(0, audited - SAMPLING_EXEMPTION_CENTS)
    issued = producer_issued_permits(producer["id"])
    active_permit = issued[0] if issued else None
    annual_cap = active_permit["annual_cap_cents"] if active_permit else 0
    cap_util = round(provisional / annual_cap * 100, 2) if annual_cap > 0 else 0
    open_complaints = sum(1 for c in DB["complaints"].values()
                          if c["producer_id"] == producer["id"]
                          and c["status"] in ("RECEIVED", "UNDER_REVIEW"))
    active_recalls = sum(1 for r in DB["recalls"].values()
                         if r["producer_id"] == producer["id"] and r["status"] == "INITIATED")
    data = {
        "producer_id": producer["id"], "status": producer["status"],
        "provisional_ytd_cents": provisional, "audited_ytd_cents": audited,
        "annual_cap_cents": annual_cap, "cap_utilization_pct": cap_util,
        "active_permit_id": active_permit["id"] if active_permit else None,
        "open_complaint_count": open_complaints, "active_recall_count": active_recalls,
    }
    return ok(data, 200)


# ===========================================================================
# AllowedFoodPolicy endpoints
# ===========================================================================
@app.route("/cottage-food/allowed-food-policies", methods=["POST"])
def create_policy():
    _uid, role = authenticate()
    authorize(role, {"HealthAdmin"})
    body = get_body()
    food_category = req_enum(body, "food_category", FOOD_CATEGORIES)
    is_cottage_allowed = req_bool(body, "is_cottage_allowed")
    class_b_required = req_bool(body, "class_b_required")
    requires_allergen_label = req_bool(body, "requires_allergen_label")
    max_ph = opt_number(body, "max_ph")
    max_water_activity = opt_number(body, "max_water_activity")
    p = base_common(with_version=False)
    p.update({
        "food_category": food_category, "is_cottage_allowed": is_cottage_allowed,
        "class_b_required": class_b_required, "requires_allergen_label": requires_allergen_label,
        "max_ph": max_ph, "max_water_activity": max_water_activity,
    })
    DB["policies"][p["id"]] = p
    return ok(s_policy(p), 201)


@app.route("/cottage-food/allowed-food-policies", methods=["GET"])
def list_policies():
    _uid, role = authenticate()
    authorize(role, {"Producer", "HealthInspector", "HealthAdmin", "MarketManager"})
    fc = request.args.get("food_category")
    items = [p for p in DB["policies"].values() if fc is None or p["food_category"] == fc]
    page, pg = paginate(items)
    return ok([s_policy(p) for p in page], 200, pg)


def policy_for_category(food_category):
    for p in DB["policies"].values():
        if p["food_category"] == food_category:
            return p
    return None


# ===========================================================================
# Product endpoints
# ===========================================================================
@app.route("/cottage-food/products", methods=["POST"])
def create_product():
    uid, role = authenticate()
    authorize(role, {"Producer"})
    body = get_body()
    producer_id = req_str(body, "producer_id")
    producer = get_producer(producer_id)
    if uid != producer["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Producers may only declare their own products")
    name = req_str(body, "name")
    food_category = req_enum(body, "food_category", FOOD_CATEGORIES)
    requires_refrigeration = req_bool(body, "requires_refrigeration")
    unit_price_cents = req_int(body, "unit_price_cents", min_value=0)
    ph_value = opt_number(body, "ph_value")
    water_activity = opt_number(body, "water_activity")
    p = base_common()
    p.update({
        "producer_id": producer_id, "name": name, "food_category": food_category,
        "requires_refrigeration": requires_refrigeration, "ph_value": ph_value,
        "water_activity": water_activity, "unit_price_cents": unit_price_cents,
        "compliance_status": "DECLARED", "label_status": "LABEL_DRAFT", "reject_reason": None,
    })
    DB["products"][p["id"]] = p
    return ok(s_product(p), 201)


@app.route("/cottage-food/products", methods=["GET"])
def list_products():
    _uid, role = authenticate()
    authorize(role, {"Producer", "HealthInspector", "HealthAdmin", "MarketManager"})
    producer_id = request.args.get("producer_id")
    compliance_status = request.args.get("compliance_status")
    items = [p for p in DB["products"].values()
             if (producer_id is None or p["producer_id"] == producer_id)
             and (compliance_status is None or p["compliance_status"] == compliance_status)]
    page, pg = paginate(items)
    return ok([s_product(p) for p in page], 200, pg)


@app.route("/cottage-food/products/<prid>", methods=["GET"])
def read_product(prid):
    _uid, role = authenticate()
    authorize(role, {"Producer", "HealthInspector", "HealthAdmin", "MarketManager"})
    return ok(s_product(get_product(prid)), 200)


@app.route("/cottage-food/products/<prid>/review-food", methods=["POST"])
def review_food(prid):
    _uid, role = authenticate()
    authorize(role, {"HealthInspector"})
    product = get_product(prid)
    body = get_body()
    decision = req_enum(body, "decision", {"APPROVE", "REJECT"})
    if product["compliance_status"] != "DECLARED":
        raise ApiError("ERR_PRODUCT_NOT_APPROVED", 422, "Product compliance axis is not in DECLARED state")
    if decision == "APPROVE":
        policy = policy_for_category(product["food_category"])
        allowed = policy is not None and policy["is_cottage_allowed"]
        if not allowed or product["requires_refrigeration"]:
            raise ApiError("ERR_FOOD_NOT_COTTAGE_ALLOWED", 422, "Product not permissible as a cottage food")
        if policy["max_ph"] is not None and product["ph_value"] is not None \
                and product["ph_value"] > policy["max_ph"]:
            raise ApiError("ERR_FOOD_NOT_COTTAGE_ALLOWED", 422, "pH exceeds acidification ceiling")
        if policy["max_water_activity"] is not None and product["water_activity"] is not None \
                and product["water_activity"] > policy["max_water_activity"]:
            raise ApiError("ERR_FOOD_NOT_COTTAGE_ALLOWED", 422, "Water activity exceeds ceiling")
        product["compliance_status"] = "APPROVED"
    else:
        product["compliance_status"] = "REJECTED"
        product["reject_reason"] = opt_str(body, "reject_reason")
    bump(product)
    return ok(s_product(product), 200)


@app.route("/cottage-food/products/<prid>/review-label", methods=["POST"])
def review_label(prid):
    _uid, role = authenticate()
    authorize(role, {"HealthInspector"})
    product = get_product(prid)
    body = get_body()
    decision = req_enum(body, "decision", {"APPROVE", "REJECT"})
    if product["label_status"] != "LABEL_DRAFT":
        raise ApiError("ERR_LABEL_NOT_APPROVED", 422, "Product label axis is not in LABEL_DRAFT state")
    if decision == "APPROVE":
        product["label_status"] = "LABEL_APPROVED"
    else:
        product["label_status"] = "LABEL_REJECTED"
        product["reject_reason"] = opt_str(body, "reject_reason")
    bump(product)
    return ok(s_product(product), 200)


# ===========================================================================
# Permit endpoints
# ===========================================================================
def permit_fee(permit_class, annual_cap):
    base = BASE_FEE_BY_CLASS[permit_class]
    if annual_cap >= 15_000_000:
        tier = 5_000
    elif annual_cap >= 7_500_000:
        tier = 2_500
    else:
        tier = 0
    inspection = INSPECTION_SURCHARGE if permit_class == "CLASS_B" else 0
    return base + tier + inspection


@app.route("/cottage-food/permits", methods=["POST"])
def create_permit():
    uid, role = authenticate()
    authorize(role, {"Producer"})
    body = get_body()
    producer_id = req_str(body, "producer_id")
    producer = get_producer(producer_id)
    if uid != producer["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Producers may only create their own permits")
    permit_class = req_enum(body, "permit_class", PERMIT_CLASSES)
    p = base_common()
    p.update({
        "producer_id": producer_id, "permit_class": permit_class, "status": "DRAFT",
        "inspection_required": permit_class == "CLASS_B", "annual_cap_cents": ANNUAL_CAP_CENTS[permit_class],
        "fee_cents": None, "term_start": None, "expires_at": None,
        "renewal_count": 0,
    })
    DB["permits"][p["id"]] = p
    return ok(s_permit(p), 201)


@app.route("/cottage-food/permits", methods=["GET"])
def list_permits():
    _uid, role = authenticate()
    authorize(role, {"Producer", "HealthInspector", "HealthAdmin", "MarketManager"})
    producer_id = request.args.get("producer_id")
    status = request.args.get("status")
    items = [p for p in DB["permits"].values()
             if (producer_id is None or p["producer_id"] == producer_id)
             and (status is None or p["status"] == status)]
    page, pg = paginate(items)
    return ok([s_permit(p) for p in page], 200, pg)


@app.route("/cottage-food/permits/<pid>", methods=["GET"])
def read_permit(pid):
    _uid, role = authenticate()
    authorize(role, {"Producer", "HealthInspector", "HealthAdmin", "MarketManager"})
    return ok(s_permit(get_permit(pid)), 200)


@app.route("/cottage-food/permits/<pid>/submit", methods=["POST"])
def submit_permit(pid):
    uid, role = authenticate()
    authorize(role, {"Producer"})
    permit = get_permit(pid)
    if uid != permit["producer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Producers may only submit their own permits")
    if permit["status"] != "DRAFT":
        raise ApiError("ERR_PERMIT_INVALID_STATE", 409, "Permit is not in DRAFT state")
    producer = DB["producers"].get(permit["producer_id"])
    if not producer or producer["status"] != "REGISTERED":
        raise ApiError("ERR_PRODUCER_NOT_REGISTERED", 409, "Acting producer is not REGISTERED")
    permit["status"] = "SUBMITTED"
    bump(permit)
    return ok(s_permit(permit), 200)


def _term_overlaps(producer_id, new_start, new_end, exclude_id):
    for other in DB["permits"].values():
        if other["id"] == exclude_id or other["producer_id"] != producer_id:
            continue
        if other["status"] != "ISSUED" or not other["term_start"] or not other["expires_at"]:
            continue
        o_start = parse_iso(other["term_start"])
        o_end = parse_iso(other["expires_at"])
        if new_start < o_end and o_start < new_end:
            return True
    return False


@app.route("/cottage-food/permits/<pid>/issue", methods=["POST"])
def issue_permit(pid):
    _uid, role = authenticate()
    authorize(role, {"HealthInspector"})
    permit = get_permit(pid)
    status = permit["status"]
    permit_class = permit["permit_class"]

    if status == "SUBMITTED":
        # CLASS_A first-issue path.
        if permit_class != "CLASS_A":
            raise ApiError("ERR_PERMIT_INVALID_STATE", 409,
                           "CLASS_B permits must pass through UNDER_INSPECTION before issue")
        start = now_dt()
        end = start + timedelta(days=PERMIT_TERM_DAYS)
        if _term_overlaps(permit["producer_id"], start, end, permit["id"]):
            raise ApiError("ERR_PERMIT_TERM_OVERLAP", 409, "Overlapping ISSUED permit term")
        permit["term_start"] = render_iso(start)
        permit["expires_at"] = render_iso(end)
        if permit["fee_cents"] is None:
            permit["fee_cents"] = permit_fee(permit_class, permit["annual_cap_cents"])
        permit["status"] = "ISSUED"
        bump(permit)
        return ok(s_permit(permit), 200)

    if status == "UNDER_INSPECTION":
        # CLASS_B first-issue path.
        passed = any(i["permit_id"] == permit["id"] and i["status"] == "PASSED"
                     for i in DB["inspections"].values())
        if not passed:
            raise ApiError("ERR_INSPECTION_NOT_PASSED", 409, "A PASSED inspection is required")
        start = now_dt()
        end = start + timedelta(days=PERMIT_TERM_DAYS)
        if _term_overlaps(permit["producer_id"], start, end, permit["id"]):
            raise ApiError("ERR_PERMIT_TERM_OVERLAP", 409, "Overlapping ISSUED permit term")
        permit["term_start"] = render_iso(start)
        permit["expires_at"] = render_iso(end)
        if permit["fee_cents"] is None:
            permit["fee_cents"] = permit_fee(permit_class, permit["annual_cap_cents"])
        permit["status"] = "ISSUED"
        bump(permit)
        return ok(s_permit(permit), 200)

    if status == "RENEWAL_PENDING":
        # Renewal re-issue path.
        if permit_class == "CLASS_B":
            passed = any(i["permit_id"] == permit["id"] and i["status"] == "PASSED"
                         and i["inspection_type"] == "RENEWAL" for i in DB["inspections"].values())
            if not passed:
                raise ApiError("ERR_INSPECTION_NOT_PASSED", 409,
                               "A PASSED RENEWAL inspection is required")
        start = now_dt()
        end = start + timedelta(days=PERMIT_TERM_DAYS)
        permit["term_start"] = render_iso(start)
        permit["expires_at"] = render_iso(end)
        permit["renewal_count"] += 1
        permit["status"] = "ISSUED"
        bump(permit)
        return ok(s_permit(permit), 200)

    raise ApiError("ERR_PERMIT_INVALID_STATE", 409, "Permit is not in an issuable state")


@app.route("/cottage-food/permits/<pid>/renew", methods=["POST"])
def renew_permit(pid):
    uid, role = authenticate()
    authorize(role, {"Producer"})
    permit = get_permit(pid)
    if uid != permit["producer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Producers may only renew their own permits")
    body = get_body()
    expected = req_int(body, "expected_permit_version")
    if permit["status"] != "ISSUED":
        raise ApiError("ERR_PERMIT_INVALID_STATE", 409, "Permit is not in ISSUED state")
    if expected != permit["version"]:
        raise ApiError("ERR_STALE_PERMIT_VERSION", 412, "expected_permit_version is stale")
    permit["status"] = "RENEWAL_PENDING"
    bump(permit)
    return ok(s_permit(permit), 200)


@app.route("/cottage-food/permits/<pid>/revoke", methods=["POST"])
def revoke_permit(pid):
    _uid, role = authenticate()
    authorize(role, {"HealthAdmin"})
    permit = get_permit(pid)
    if permit["status"] == "REVOKED":
        raise ApiError("ERR_PERMIT_INVALID_STATE", 409, "Permit already REVOKED")
    was_issued = permit["status"] == "ISSUED"
    permit["status"] = "REVOKED"
    bump(permit)
    if was_issued:
        revoke_permit_cascade(permit)
    return ok(s_permit(permit), 200)


# ===========================================================================
# Inspection endpoints
# ===========================================================================
@app.route("/cottage-food/inspections", methods=["POST"])
def create_inspection():
    _uid, role = authenticate()
    authorize(role, {"HealthInspector"})
    body = get_body()
    permit_id = req_str(body, "permit_id")
    permit = get_permit(permit_id)
    inspection_type = req_enum(body, "inspection_type", INSPECTION_TYPES)
    scheduled_for = req_str(body, "scheduled_for")
    i = base_common()
    i.update({
        "permit_id": permit_id, "inspection_type": inspection_type, "status": "SCHEDULED",
        "scheduled_for": scheduled_for, "violation_count": 0, "inspector_user_id": None,
    })
    DB["inspections"][i["id"]] = i
    # Scheduling against a SUBMITTED permit advances it to UNDER_INSPECTION.
    if permit["status"] == "SUBMITTED":
        permit["status"] = "UNDER_INSPECTION"
        bump(permit)
    return ok(s_inspection(i), 201)


@app.route("/cottage-food/inspections", methods=["GET"])
def list_inspections():
    _uid, role = authenticate()
    authorize(role, {"Producer", "HealthInspector", "HealthAdmin"})
    permit_id = request.args.get("permit_id")
    status = request.args.get("status")
    items = [i for i in DB["inspections"].values()
             if (permit_id is None or i["permit_id"] == permit_id)
             and (status is None or i["status"] == status)]
    page, pg = paginate(items)
    return ok([s_inspection(i) for i in page], 200, pg)


@app.route("/cottage-food/inspections/<iid>", methods=["GET"])
def read_inspection(iid):
    _uid, role = authenticate()
    authorize(role, {"Producer", "HealthInspector", "HealthAdmin"})
    return ok(s_inspection(get_inspection(iid)), 200)


@app.route("/cottage-food/inspections/<iid>/close", methods=["POST"])
def close_inspection(iid):
    uid, role = authenticate()
    authorize(role, {"HealthInspector"})
    inspection = get_inspection(iid)
    body = get_body()
    result = req_enum(body, "result", {"PASS", "FAIL"})
    violation_count = 0
    if "violation_count" in body and body["violation_count"] is not None:
        violation_count = req_int(body, "violation_count", min_value=0)
    if inspection["status"] != "SCHEDULED":
        raise ApiError("ERR_INSPECTION_NOT_SCHEDULED", 409, "Inspection is not SCHEDULED")
    inspection["status"] = "PASSED" if result == "PASS" else "FAILED"
    inspection["violation_count"] = violation_count
    inspection["inspector_user_id"] = uid
    bump(inspection)
    return ok(s_inspection(inspection), 200)


# ===========================================================================
# Complaint endpoints
# ===========================================================================
@app.route("/cottage-food/complaints", methods=["POST"])
def create_complaint():
    uid, role = authenticate()
    authorize(role, {"HealthInspector", "HealthAdmin"})
    body = get_body()
    producer_id = req_str(body, "producer_id")
    get_producer(producer_id)
    product_id = opt_str(body, "product_id")
    if product_id is not None:
        get_product(product_id)
    category = req_enum(body, "category", COMPLAINT_CATEGORIES)
    description = req_str(body, "description")
    c = base_common()
    c.update({
        "producer_id": producer_id, "product_id": product_id, "category": category,
        "description": description, "status": "RECEIVED", "filed_by_user_id": uid,
        "reviewed_by_user_id": None,
    })
    DB["complaints"][c["id"]] = c
    return ok(s_complaint(c), 201)


@app.route("/cottage-food/complaints", methods=["GET"])
def list_complaints():
    _uid, role = authenticate()
    authorize(role, {"HealthInspector", "HealthAdmin"})
    producer_id = request.args.get("producer_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    items = [c for c in DB["complaints"].values()
             if (producer_id is None or c["producer_id"] == producer_id)
             and (product_id is None or c["product_id"] == product_id)
             and (status is None or c["status"] == status)]
    page, pg = paginate(items)
    return ok([s_complaint(c) for c in page], 200, pg)


@app.route("/cottage-food/complaints/<cid>", methods=["GET"])
def read_complaint(cid):
    _uid, role = authenticate()
    authorize(role, {"HealthInspector", "HealthAdmin"})
    return ok(s_complaint(get_complaint(cid)), 200)


@app.route("/cottage-food/complaints/<cid>/review", methods=["POST"])
def review_complaint(cid):
    uid, role = authenticate()
    authorize(role, {"HealthInspector", "HealthAdmin"})
    complaint = get_complaint(cid)
    if complaint["status"] != "RECEIVED":
        raise ApiError("ERR_COMPLAINT_INVALID_STATE", 409, "Complaint is not in RECEIVED state")
    if uid == complaint["filed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "Reviewer must differ from filer")
    complaint["status"] = "UNDER_REVIEW"
    complaint["reviewed_by_user_id"] = uid
    bump(complaint)
    return ok(s_complaint(complaint), 200)


@app.route("/cottage-food/complaints/<cid>/resolve", methods=["POST"])
def resolve_complaint(cid):
    uid, role = authenticate()
    authorize(role, {"HealthInspector", "HealthAdmin"})
    complaint = get_complaint(cid)
    body = get_body()
    outcome = req_enum(body, "outcome", {"SUBSTANTIATE", "DISMISS"})
    if complaint["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_COMPLAINT_INVALID_STATE", 409, "Complaint is not in UNDER_REVIEW state")
    if uid == complaint["filed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "Resolver must differ from filer")
    complaint["status"] = "SUBSTANTIATED" if outcome == "SUBSTANTIATE" else "DISMISSED"
    bump(complaint)
    return ok(s_complaint(complaint), 200)


# ===========================================================================
# FarmersMarket endpoints
# ===========================================================================
@app.route("/cottage-food/farmers-markets", methods=["POST"])
def create_market():
    _uid, role = authenticate()
    authorize(role, {"HealthAdmin"})
    body = get_body()
    name = req_str(body, "name")
    county = req_str(body, "county")
    venue_type = req_enum(body, "venue_type", VENUE_TYPES)
    max_vendors = req_int(body, "max_vendors_per_day", min_value=0)
    if "allowed_classes" not in body or not isinstance(body["allowed_classes"], list):
        inv("allowed_classes must be a list")
    allowed_classes = body["allowed_classes"]
    for c in allowed_classes:
        if c not in PERMIT_CLASSES:
            inv("allowed_classes contains an illegal value")
    m = base_common()
    m.update({
        "name": name, "county": county, "venue_type": venue_type,
        "max_vendors_per_day": max_vendors, "allowed_classes": allowed_classes, "status": "ACTIVE",
    })
    DB["markets"][m["id"]] = m
    return ok(s_market(m), 201)


@app.route("/cottage-food/farmers-markets", methods=["GET"])
def list_markets():
    _uid, role = authenticate()
    authorize(role, {"Producer", "HealthInspector", "HealthAdmin", "MarketManager"})
    county = request.args.get("county")
    venue_type = request.args.get("venue_type")
    items = [m for m in DB["markets"].values()
             if (county is None or m["county"] == county)
             and (venue_type is None or m["venue_type"] == venue_type)]
    page, pg = paginate(items)
    return ok([s_market(m) for m in page], 200, pg)


@app.route("/cottage-food/farmers-markets/<mid>", methods=["GET"])
def read_market(mid):
    _uid, role = authenticate()
    authorize(role, {"Producer", "HealthInspector", "HealthAdmin", "MarketManager"})
    return ok(s_market(get_market(mid)), 200)


# ===========================================================================
# MarketManifest endpoints
# ===========================================================================
@app.route("/cottage-food/market-manifests", methods=["POST"])
def create_manifest():
    uid, role = authenticate()
    authorize(role, {"Producer"})
    body = get_body()
    producer_id = req_str(body, "producer_id")
    producer = get_producer(producer_id)
    if uid != producer["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Producers may only create their own manifests")
    market_id = req_str(body, "market_id")
    get_market(market_id)
    permit_id = req_str(body, "permit_id")
    get_permit(permit_id)
    if "event_date" not in body or not isinstance(body.get("event_date"), str) \
            or not EVENT_DATE_RE.match(body["event_date"]):
        inv("event_date must be a YYYY-MM-DD string")
    event_date = body["event_date"]
    if "product_ids" not in body or not isinstance(body["product_ids"], list):
        inv("product_ids must be a list")
    product_ids = body["product_ids"]
    for prid in product_ids:
        if not isinstance(prid, str):
            inv("product_ids must contain strings")
        get_product(prid)
    m = base_common()
    m.update({
        "producer_id": producer_id, "market_id": market_id, "permit_id": permit_id,
        "event_date": event_date, "product_ids": product_ids, "status": "DRAFT",
        "booth_fee_cents": 0,
    })
    DB["manifests"][m["id"]] = m
    return ok(s_manifest(m), 201)


@app.route("/cottage-food/market-manifests", methods=["GET"])
def list_manifests():
    _uid, role = authenticate()
    authorize(role, {"Producer", "HealthInspector", "HealthAdmin", "MarketManager"})
    producer_id = request.args.get("producer_id")
    market_id = request.args.get("market_id")
    permit_id = request.args.get("permit_id")
    status = request.args.get("status")
    event_date = request.args.get("event_date")
    items = [m for m in DB["manifests"].values()
             if (producer_id is None or m["producer_id"] == producer_id)
             and (market_id is None or m["market_id"] == market_id)
             and (permit_id is None or m["permit_id"] == permit_id)
             and (status is None or m["status"] == status)
             and (event_date is None or m["event_date"] == event_date)]
    page, pg = paginate(items)
    return ok([s_manifest(m) for m in page], 200, pg)


@app.route("/cottage-food/market-manifests/<mid>", methods=["GET"])
def read_manifest(mid):
    _uid, role = authenticate()
    authorize(role, {"Producer", "HealthInspector", "HealthAdmin", "MarketManager"})
    return ok(s_manifest(get_manifest(mid)), 200)


@app.route("/cottage-food/market-manifests/<mid>/submit", methods=["POST"])
def submit_manifest(mid):
    uid, role = authenticate()
    authorize(role, {"Producer"})
    manifest = get_manifest(mid)
    if uid != manifest["producer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Producers may only submit their own manifests")
    if manifest["status"] != "DRAFT":
        raise ApiError("ERR_MANIFEST_INVALID_STATE", 409, "Manifest is not in DRAFT state")
    producer = DB["producers"].get(manifest["producer_id"])
    permit = DB["permits"].get(manifest["permit_id"])
    market = DB["markets"].get(manifest["market_id"])
    # 1. Producer REGISTERED.
    if not producer or producer["status"] != "REGISTERED":
        raise ApiError("ERR_PRODUCER_NOT_REGISTERED", 409, "Acting producer is not REGISTERED")
    # 2. Permit ISSUED.
    if not permit or permit["status"] != "ISSUED":
        raise ApiError("ERR_PERMIT_NOT_ISSUED", 409, "Linked permit is not ISSUED")
    # 3. Products approved / label-approved / not recalled.
    for prid in manifest["product_ids"]:
        product = DB["products"].get(prid)
        if not product:
            raise ApiError("ERR_PRODUCT_NOT_FOUND", 404, "Product no longer exists")
        if product["compliance_status"] == "RECALLED":
            raise ApiError("ERR_PRODUCT_RECALLED", 422, "A manifest product is RECALLED")
        if product["compliance_status"] != "APPROVED":
            raise ApiError("ERR_PRODUCT_NOT_APPROVED", 422, "A manifest product is not APPROVED")
        if product["label_status"] != "LABEL_APPROVED":
            raise ApiError("ERR_LABEL_NOT_APPROVED", 422, "A manifest product is not LABEL_APPROVED")
    # 4. Venue class restriction.
    if permit["permit_class"] not in market["allowed_classes"]:
        raise ApiError("ERR_VENUE_CLASS_NOT_ALLOWED", 422, "Permit class not allowed at this venue")
    # 5. Permit not expired at event_date.
    if manifest["event_date"] > permit["expires_at"][:10]:
        raise ApiError("ERR_PERMIT_EXPIRED", 409, "Permit is expired at the event date")
    # 6. No duplicate non-terminal manifest for (producer, market, event_date).
    for other in DB["manifests"].values():
        if other["id"] == manifest["id"]:
            continue
        if (other["producer_id"] == manifest["producer_id"]
                and other["market_id"] == manifest["market_id"]
                and other["event_date"] == manifest["event_date"]
                and other["status"] in MANIFEST_NON_TERMINAL):
            raise ApiError("ERR_DUPLICATE_MANIFEST", 409, "Duplicate manifest for this event")
    manifest["status"] = "SUBMITTED"
    bump(manifest)
    return ok(s_manifest(manifest), 200)


@app.route("/cottage-food/market-manifests/<mid>/approve", methods=["POST"])
def approve_manifest(mid):
    uid, role = authenticate()
    authorize(role, {"MarketManager"})
    manifest = get_manifest(mid)
    if uid != manifest["market_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "MarketManager may only act on their own market")
    body = get_body()
    expected = req_int(body, "expected_market_version")
    if manifest["status"] != "SUBMITTED":
        raise ApiError("ERR_MANIFEST_INVALID_STATE", 409, "Manifest is not in SUBMITTED state")
    market = DB["markets"].get(manifest["market_id"])
    if expected != market["version"]:
        raise ApiError("ERR_STALE_MARKET_VERSION", 412, "expected_market_version is stale")
    if market_day_occupancy(manifest["market_id"], manifest["event_date"]) >= market["max_vendors_per_day"]:
        raise ApiError("ERR_MARKET_CAPACITY_FULL", 409, "Market day-slot capacity reached")
    manifest["status"] = "APPROVED"
    bump(manifest)
    bump(market)  # occupy one day-slot
    return ok(s_manifest(manifest), 200)


@app.route("/cottage-food/market-manifests/<mid>/reject", methods=["POST"])
def reject_manifest(mid):
    uid, role = authenticate()
    authorize(role, {"MarketManager"})
    manifest = get_manifest(mid)
    if uid != manifest["market_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "MarketManager may only act on their own market")
    if manifest["status"] != "SUBMITTED":
        raise ApiError("ERR_MANIFEST_INVALID_STATE", 409, "Manifest is not in SUBMITTED state")
    manifest["status"] = "REJECTED"
    bump(manifest)
    return ok(s_manifest(manifest), 200)


@app.route("/cottage-food/market-manifests/<mid>/check-in", methods=["POST"])
def checkin_manifest(mid):
    uid, role = authenticate()
    authorize(role, {"MarketManager"})
    manifest = get_manifest(mid)
    if uid != manifest["market_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "MarketManager may only act on their own market")
    if manifest["status"] != "APPROVED":
        raise ApiError("ERR_MANIFEST_INVALID_STATE", 409, "Manifest is not in APPROVED state")
    manifest["status"] = "CHECKED_IN"
    bump(manifest)
    return ok(s_manifest(manifest), 200)


@app.route("/cottage-food/market-manifests/<mid>/withdraw", methods=["POST"])
def withdraw_manifest(mid):
    uid, role = authenticate()
    authorize(role, {"Producer"})
    manifest = get_manifest(mid)
    if uid != manifest["producer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Producers may only withdraw their own manifests")
    if manifest["status"] not in ("SUBMITTED", "APPROVED"):
        raise ApiError("ERR_MANIFEST_INVALID_STATE", 409, "Manifest is not in a withdrawable state")
    was_approved = manifest["status"] == "APPROVED"
    manifest["status"] = "WITHDRAWN"
    bump(manifest)
    if was_approved:
        market = DB["markets"].get(manifest["market_id"])
        if market:
            bump(market)  # release day-slot
    return ok(s_manifest(manifest), 200)


# ===========================================================================
# SalesRecord endpoints
# ===========================================================================
@app.route("/cottage-food/sales-records", methods=["POST"])
def create_sales_record():
    uid, role = authenticate()
    authorize(role, {"Producer"})
    body = get_body()
    manifest_id = req_str(body, "manifest_id")
    manifest = get_manifest(manifest_id)
    if uid != manifest["producer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Producers may only report their own sales")
    gross = req_int(body, "gross_amount_cents", strict_min=0)
    if manifest["status"] not in ("APPROVED", "CHECKED_IN"):
        raise ApiError("ERR_MANIFEST_INVALID_STATE", 409, "Manifest is not APPROVED or CHECKED_IN")
    producer = DB["producers"].get(manifest["producer_id"])
    if not producer or producer["status"] != "REGISTERED":
        raise ApiError("ERR_PRODUCER_NOT_REGISTERED", 409, "Acting producer is not REGISTERED")
    s = base_common()
    s.update({
        "manifest_id": manifest_id, "producer_id": manifest["producer_id"],
        "gross_amount_cents": gross, "status": "RECORDED", "recorded_at": now_iso(),
    })
    DB["sales"][s["id"]] = s
    # Side effect 1: ledger add.
    recompute_ytd(producer)
    # Side effect 2: booth fee recompute.
    recompute_booth_fee(manifest)
    # Side effect 3: cap-breach check on provisional ytd.
    issued = producer_issued_permits(producer["id"])
    if issued:
        cap = issued[0]["annual_cap_cents"]
        if producer["ytd_gross_sales_cents"] > cap:
            suspend_producer_cascade(producer)
    return ok(s_sale(s), 201)


@app.route("/cottage-food/sales-records", methods=["GET"])
def list_sales_records():
    _uid, role = authenticate()
    authorize(role, {"Producer", "HealthInspector", "HealthAdmin"})
    manifest_id = request.args.get("manifest_id")
    producer_id = request.args.get("producer_id")
    status = request.args.get("status")
    items = [s for s in DB["sales"].values()
             if (manifest_id is None or s["manifest_id"] == manifest_id)
             and (producer_id is None or s["producer_id"] == producer_id)
             and (status is None or s["status"] == status)]
    page, pg = paginate(items)
    return ok([s_sale(s) for s in page], 200, pg)


@app.route("/cottage-food/sales-records/<sid>", methods=["GET"])
def read_sales_record(sid):
    _uid, role = authenticate()
    authorize(role, {"Producer", "HealthInspector", "HealthAdmin"})
    return ok(s_sale(get_sale(sid)), 200)


@app.route("/cottage-food/sales-records/<sid>/void", methods=["POST"])
def void_sales_record(sid):
    _uid, role = authenticate()
    authorize(role, {"HealthAdmin"})
    sale = get_sale(sid)
    if sale["status"] != "RECORDED":
        raise ApiError("ERR_SALES_RECORD_NOT_RECORDED", 409, "Sales record is not RECORDED")
    sale["status"] = "VOIDED"
    bump(sale)
    producer = DB["producers"].get(sale["producer_id"])
    if producer:
        recompute_ytd(producer)
    manifest = DB["manifests"].get(sale["manifest_id"])
    if manifest:
        recompute_booth_fee(manifest)
    return ok(s_sale(sale), 200)


# ===========================================================================
# RecallEvent endpoints
# ===========================================================================
@app.route("/cottage-food/recall-events", methods=["POST"])
def create_recall():
    _uid, role = authenticate()
    authorize(role, {"HealthAdmin"})
    body = get_body()
    producer_id = req_str(body, "producer_id")
    producer = get_producer(producer_id)
    product_id = req_str(body, "product_id")
    product = get_product(product_id)
    reason = req_enum(body, "reason", RECALL_REASONS)
    severity = req_enum(body, "severity", SEVERITIES)
    if product["compliance_status"] != "APPROVED":
        raise ApiError("ERR_PRODUCT_NOT_APPROVED", 422, "Recall target product is not APPROVED")
    estimated = PROJECTED_UNITS_BY_SEVERITY[severity] * product["unit_price_cents"]
    r = base_common()
    r.update({
        "producer_id": producer_id, "product_id": product_id, "reason": reason,
        "severity": severity, "status": "INITIATED", "recalled_units": 0,
        "estimated_liability_cents": estimated, "final_liability_cents": None,
    })
    DB["recalls"][r["id"]] = r
    # Cascade: product -> RECALLED, then producer + issued permit suspend + void manifests.
    product["compliance_status"] = "RECALLED"
    bump(product)
    suspend_producer_cascade(producer)
    return ok(s_recall(r), 201)


@app.route("/cottage-food/recall-events", methods=["GET"])
def list_recalls():
    _uid, role = authenticate()
    authorize(role, {"Producer", "HealthInspector", "HealthAdmin"})
    producer_id = request.args.get("producer_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    items = [r for r in DB["recalls"].values()
             if (producer_id is None or r["producer_id"] == producer_id)
             and (product_id is None or r["product_id"] == product_id)
             and (status is None or r["status"] == status)]
    page, pg = paginate(items)
    return ok([s_recall(r) for r in page], 200, pg)


@app.route("/cottage-food/recall-events/<rid>", methods=["GET"])
def read_recall(rid):
    _uid, role = authenticate()
    authorize(role, {"Producer", "HealthInspector", "HealthAdmin"})
    return ok(s_recall(get_recall(rid)), 200)


@app.route("/cottage-food/recall-events/<rid>/resolve", methods=["POST"])
def resolve_recall(rid):
    _uid, role = authenticate()
    authorize(role, {"HealthAdmin"})
    recall = get_recall(rid)
    body = get_body()
    recalled_units = req_int(body, "recalled_units", min_value=0)
    if recall["status"] != "INITIATED":
        raise ApiError("ERR_RECALL_INVALID_STATE", 409, "Recall is not INITIATED")
    product = DB["products"].get(recall["product_id"])
    unit_price = product["unit_price_cents"] if product else 0
    recall["recalled_units"] = recalled_units
    recall["final_liability_cents"] = recalled_units * unit_price
    recall["status"] = "RESOLVED"
    bump(recall)
    return ok(s_recall(recall), 200)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = authenticate()
    authorize(role, {"HealthAdmin"})
    body = get_body()
    to_iso = req_str(body, "to_iso8601")
    try:
        dt = parse_iso(to_iso)
    except (ValueError, TypeError):
        inv("to_iso8601 is not a valid ISO-8601 instant")
    _CLOCK["dt"] = dt
    return ok({"current_utc": to_iso}, 200)


# ===========================================================================
# Liveness
# ===========================================================================
@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


_reset_clock()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
