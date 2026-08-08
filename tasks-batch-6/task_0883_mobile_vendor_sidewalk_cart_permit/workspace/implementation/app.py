import os
import uuid
import random
import string
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__, static_folder=None)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VALID_ROLES = {"Vendor", "PermitOfficer", "HealthInspector", "EnforcementOfficer", "Resident"}

MIN_INSURANCE_COVERAGE_CENTS = 100000000
PERMIT_TERM_DAYS = 365
RENEWAL_GRACE_DAYS = 30
SUSPENSION_POINT_THRESHOLD = 12
VIOLATION_POINT_WINDOW_DAYS = 365

PERMIT_BASE_FEE_CENTS = 20000
ZONE_SURCHARGE_CENTS = {"PRIME": 15000, "STANDARD": 5000}
CART_SIZE_FEE_CENTS = {"SMALL": 3500, "MEDIUM": 6500, "LARGE": 11000}
FEE_TAX_RATE = Decimal("0.0875")
RENEWAL_BASE_FACTOR = Decimal("0.80")
RENEWAL_LATE_PENALTY_CENTS = 7500

IMPOUND_BASE_FEE_CENTS = 10000
IMPOUND_ADMIN_FEE_CENTS = 5000
STORAGE_TIER1_DAYS = 7
STORAGE_DAILY_RATE1_CENTS = 2500
STORAGE_DAILY_RATE2_CENTS = 4000

VIOLATION_POINTS = {"MINOR": 3, "MAJOR": 6, "CRITICAL": 12}
VIOLATION_FINE_CENTS = {"MINOR": 5000, "MAJOR": 12000, "CRITICAL": 30000}

LOTTERY_W_SENIORITY = 10
LOTTERY_W_COMPLIANCE = 1
LOTTERY_W_VIOLATION = 5

DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

CART_TYPES = {"FOOD", "PRODUCE", "MERCHANDISE"}
PERMIT_TYPES = {"FOOD", "PRODUCE", "MERCHANDISE"}
HEALTH_GRADES = {"A", "B", "C"}
ZONE_TYPES = {"PRIME", "STANDARD"}
VIOLATION_TYPES = {"MINOR", "MAJOR", "CRITICAL"}
COMPLAINT_TYPES = {"NOISE", "SANITATION", "BLOCKING", "UNPERMITTED"}
IMPOUND_REASONS = {"UNPERMITTED", "HEALTH_HAZARD", "ABANDONMENT", "SPACING"}
ADJ_OUTCOMES = {"UPHOLD", "DISMISS"}
RESOLUTION_OUTCOMES = {"SUBSTANTIATED", "UNFOUNDED"}
INSPECT_RESULTS = {"PASS", "FAIL"}
COMMISSARY_STATUS = {"ACTIVE", "SUSPENDED"}

# ---------------------------------------------------------------------------
# In-memory store (empty on every boot — never seeded)
# ---------------------------------------------------------------------------
DB = {
    "vendors": {},
    "commissaries": {},
    "carts": {},
    "zones": {},
    "spots": {},
    "permits": {},
    "lotteries": {},
    "lottery_entries": {},
    "spot_assignments": {},
    "violations": {},
    "impounds": {},
    "complaints": {},
}

CLOCK = {"now": None}
_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def now():
    return CLOCK["now"]


CLOCK["now"] = parse_iso(DEFAULT_CLOCK)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def make_meta(pagination=None):
    meta = {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": fmt_iso(now()),
    }
    if pagination:
        meta.update(pagination)
    return meta


def resp_object(data, code=200):
    return jsonify({"meta": make_meta(), "response_type": "object", "data": data}), code


def resp_array(items, limit, offset, total, code=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return jsonify({"meta": make_meta(pagination), "response_type": "array", "data": items}), code


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Auth / RBAC helpers
# ---------------------------------------------------------------------------
def get_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


def get_body():
    body = request.get_json(silent=True, force=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return body


def require_str(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", 400, "Missing required field: %s" % field)
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be a non-empty string" % field)
    return v


def require_int(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", 400, "Missing required field: %s" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be an integer" % field)
    return v


def require_datetime(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", 400, "Missing required field: %s" % field)
    v = body[field]
    try:
        parse_iso(v)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "Field %s must be an ISO8601 datetime" % field)
    return v


def check_enum(value, allowed, field="value"):
    if value not in allowed:
        raise ApiError("ERR_INVALID_ENUM", 422, "Invalid enum for %s" % field)
    return value


def find(store, _id):
    ent = DB[store].get(_id)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return ent


# ---------------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------------
def base_fields():
    ts = fmt_iso(now())
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(ent):
    ent["updated_at"] = fmt_iso(now())
    ent["version"] += 1


def charge(vendor, cents):
    vendor["total_charged_cents"] += cents
    touch(vendor)


def credit(vendor, cents):
    vendor["total_credited_cents"] += cents
    touch(vendor)


def mul_rhu(cents, rate):
    return int((Decimal(cents) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Computed field helpers
# ---------------------------------------------------------------------------
def vendor_permits(vendor_id):
    return [p for p in DB["permits"].values() if p["vendor_id"] == vendor_id]


def insurance_status(v):
    if v.get("insurance_effective_at") is None:
        return "NONE"
    eff = parse_iso(v["insurance_effective_at"])
    exp = parse_iso(v["insurance_expires_at"])
    if eff <= now() < exp and v["insurance_coverage_cents"] >= MIN_INSURANCE_COVERAGE_CENTS:
        return "ACTIVE"
    return "LAPSED"


def compliance_score(v):
    permit_ids = {p["id"] for p in vendor_permits(v["id"])}
    upheld = sum(
        1 for vio in DB["violations"].values()
        if vio["permit_id"] in permit_ids and vio["status"] == "UPHELD"
    )
    return max(0, min(100, 100 - 5 * upheld))


def permit_violation_points(p):
    cutoff = now() - timedelta(days=VIOLATION_POINT_WINDOW_DAYS)
    total = 0
    for vio in DB["violations"].values():
        if vio["permit_id"] != p["id"]:
            continue
        if vio["status"] != "UPHELD":
            continue
        if parse_iso(vio["updated_at"]) >= cutoff:
            total += VIOLATION_POINTS[vio["violation_type"]]
    return total


def zone_assigned_slots(z):
    return sum(
        1 for a in DB["spot_assignments"].values()
        if a["zone_id"] == z["id"] and a["status"] == "ACTIVE"
    )


def spot_status(s):
    for a in DB["spot_assignments"].values():
        if a["spot_id"] == s["id"] and a["status"] == "ACTIVE":
            return "ASSIGNED"
    return "AVAILABLE"


def lottery_awarded_count(l):
    return sum(
        1 for e in DB["lottery_entries"].values()
        if e["lottery_id"] == l["id"] and e["status"] == "AWARDED"
    )


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def pub(ent, extra):
    out = {"id": ent["id"], "created_at": ent["created_at"],
           "updated_at": ent["updated_at"], "version": ent["version"]}
    out.update(extra)
    return out


def ser_vendor(v):
    return pub(v, {
        "legal_name": v["legal_name"],
        "contact_email": v["contact_email"],
        "seniority_years": v["seniority_years"],
        "status": v["status"],
        "insurance_effective_at": v.get("insurance_effective_at"),
        "insurance_expires_at": v.get("insurance_expires_at"),
        "insurance_coverage_cents": v["insurance_coverage_cents"],
        "insurance_status": insurance_status(v),
        "total_charged_cents": v["total_charged_cents"],
        "total_credited_cents": v["total_credited_cents"],
        "balance_owed_cents": v["total_charged_cents"] - v["total_credited_cents"],
        "compliance_score": compliance_score(v),
    })


def ser_commissary(c):
    return pub(c, {
        "name": c["name"],
        "health_grade": c["health_grade"],
        "license_expires_at": c["license_expires_at"],
        "status": c["status"],
    })


def ser_cart(c):
    return pub(c, {
        "vendor_id": c["vendor_id"],
        "commissary_id": c["commissary_id"],
        "cart_type": c["cart_type"],
        "size_sqft": c["size_sqft"],
        "inspection_status": c["_inspection_result"] if c["_inspection_result"] else "PENDING",
        "inspection_score": c["inspection_score"],
        "inspection_expires_at": c["inspection_expires_at"],
        "status": c["status"],
    })


def ser_zone(z):
    assigned = zone_assigned_slots(z)
    return pub(z, {
        "name": z["name"],
        "zone_type": z["zone_type"],
        "capacity_slots": z["capacity_slots"],
        "spacing_min_feet": z["spacing_min_feet"],
        "assigned_slots": assigned,
        "available_slots": z["capacity_slots"] - assigned,
        "status": z["status"],
    })


def ser_spot(s):
    return pub(s, {
        "zone_id": s["zone_id"],
        "label": s["label"],
        "position_feet": s["position_feet"],
        "status": spot_status(s),
    })


def ser_permit(p):
    return pub(p, {
        "vendor_id": p["vendor_id"],
        "cart_id": p["cart_id"],
        "zone_id": p["zone_id"],
        "permit_type": p["permit_type"],
        "status": p["status"],
        "fee_variant": p["fee_variant"],
        "fee_amount_cents": p["fee_amount_cents"],
        "issued_at": p["issued_at"],
        "expires_at": p["expires_at"],
        "violation_points": permit_violation_points(p),
    })


def ser_lottery(l):
    return pub(l, {
        "zone_id": l["zone_id"],
        "entry_fee_cents": l["entry_fee_cents"],
        "term_start_at": l["term_start_at"],
        "term_end_at": l["term_end_at"],
        "status": l["status"],
        "awarded_count": lottery_awarded_count(l),
    })


def ser_entry(e):
    return pub(e, {
        "lottery_id": e["lottery_id"],
        "permit_id": e["permit_id"],
        "preferred_spot_ids": e["preferred_spot_ids"],
        "rank_score": e["rank_score"],
        "awarded_spot_id": e["awarded_spot_id"],
        "status": e["status"],
    })


def ser_assignment(a):
    return pub(a, {
        "spot_id": a["spot_id"],
        "permit_id": a["permit_id"],
        "zone_id": a["zone_id"],
        "position_feet": a["position_feet"],
        "start_at": a["start_at"],
        "end_at": a["end_at"],
        "origin": a["origin"],
        "status": a["status"],
    })


def ser_violation(v):
    return pub(v, {
        "permit_id": v["permit_id"],
        "violation_type": v["violation_type"],
        "description": v["description"],
        "points": v["points"],
        "fine_cents": v["fine_cents"],
        "issuer_user_id": v["issuer_user_id"],
        "source_complaint_id": v["source_complaint_id"],
        "status": v["status"],
    })


def ser_impound(i):
    return pub(i, {
        "cart_id": i["cart_id"],
        "reason": i["reason"],
        "impounded_at": i["impounded_at"],
        "settled_at": i["settled_at"],
        "storage_days": i["storage_days"],
        "settlement_variant": i["settlement_variant"],
        "release_fee_cents": i["release_fee_cents"],
        "municipal_writeoff_cents": i["municipal_writeoff_cents"],
        "status": i["status"],
    })


def ser_complaint(c):
    return pub(c, {
        "permit_id": c["permit_id"],
        "complaint_type": c["complaint_type"],
        "description": c["description"],
        "resolution": c["resolution"],
        "generated_violation_id": c["generated_violation_id"],
        "status": c["status"],
    })


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def get_pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            limit = 10
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            offset = 0
    if limit > 100:
        limit = 100
    if limit < 1:
        limit = 1
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(items, serializer):
    items = sorted(items, key=lambda e: e["_seq"])
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return resp_array([serializer(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Cascade helpers
# ---------------------------------------------------------------------------
def release_assignment(a):
    a["status"] = "RELEASED"
    touch(a)
    zone = DB["zones"].get(a["zone_id"])
    if zone is not None:
        touch(zone)  # bump zone.version (and updated_at)


def suspend_permit_from_issued(p):
    """Suspend an ISSUED permit and cascade-release its ACTIVE assignments."""
    if p["status"] != "ISSUED":
        return
    p["status"] = "SUSPENDED"
    touch(p)
    for a in DB["spot_assignments"].values():
        if a["permit_id"] == p["id"] and a["status"] == "ACTIVE":
            release_assignment(a)


def size_tier(sqft):
    if sqft <= 20:
        return "SMALL"
    if sqft <= 40:
        return "MEDIUM"
    return "LARGE"


def compute_permit_fee(variant, zone, cart):
    if variant == "RENEWAL_EARLY":
        base = mul_rhu(PERMIT_BASE_FEE_CENTS, RENEWAL_BASE_FACTOR)
    else:
        base = PERMIT_BASE_FEE_CENTS
    zone_c = ZONE_SURCHARGE_CENTS[zone["zone_type"]]
    size_c = CART_SIZE_FEE_CENTS[size_tier(cart["size_sqft"])]
    tax = mul_rhu(base, FEE_TAX_RATE) + mul_rhu(zone_c, FEE_TAX_RATE) + mul_rhu(size_c, FEE_TAX_RATE)
    fee = base + zone_c + size_c + tax
    if variant == "RENEWAL_LATE":
        fee += RENEWAL_LATE_PENALTY_CENTS
    return fee


def compute_storage_days(impounded_at, settled_at):
    delta = parse_iso(settled_at) - parse_iso(impounded_at)
    secs = delta.total_seconds()
    days = math.ceil(secs / 86400.0)
    return max(1, int(days))


def compute_storage_cost(days):
    tier1 = min(days, STORAGE_TIER1_DAYS)
    tier2 = max(0, days - STORAGE_TIER1_DAYS)
    return tier1 * STORAGE_DAILY_RATE1_CENTS + tier2 * STORAGE_DAILY_RATE2_CENTS


# ===========================================================================
# System / clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_auth()
    authorize(role, {"PermitOfficer"})
    body = get_body()
    ts = require_datetime(body, "to_iso8601")
    CLOCK["now"] = parse_iso(ts)
    return resp_object({}, 200)


# ===========================================================================
# Vendor
# ===========================================================================
@app.route("/vendors", methods=["POST"])
def create_vendor():
    _, role = get_auth()
    authorize(role, {"PermitOfficer"})
    body = get_body()
    legal_name = require_str(body, "legal_name")
    contact_email = require_str(body, "contact_email")
    seniority = 0
    if body.get("seniority_years") is not None:
        seniority = require_int(body, "seniority_years")
    v = base_fields()
    v.update({
        "legal_name": legal_name,
        "contact_email": contact_email,
        "seniority_years": seniority,
        "status": "ACTIVE",
        "insurance_effective_at": None,
        "insurance_expires_at": None,
        "insurance_coverage_cents": 0,
        "total_charged_cents": 0,
        "total_credited_cents": 0,
    })
    DB["vendors"][v["id"]] = v
    return resp_object(ser_vendor(v), 201)


@app.route("/vendors/<vid>", methods=["GET"])
def get_vendor(vid):
    _, role = get_auth()
    authorize(role, {"Vendor", "PermitOfficer", "EnforcementOfficer", "HealthInspector"})
    v = find("vendors", vid)
    return resp_object(ser_vendor(v), 200)


@app.route("/vendors/<vid>/insurance", methods=["POST"])
def submit_insurance(vid):
    uid, role = get_auth()
    authorize(role, {"Vendor"})
    if uid != vid:
        raise ApiError("ERR_OWNERSHIP", 403, "Vendor may only act on its own record")
    v = find("vendors", vid)
    body = get_body()
    eff = require_datetime(body, "insurance_effective_at")
    exp = require_datetime(body, "insurance_expires_at")
    cov = require_int(body, "insurance_coverage_cents")
    if cov < MIN_INSURANCE_COVERAGE_CENTS:
        raise ApiError("ERR_INSUFFICIENT_COVERAGE", 422, "Coverage below minimum liability requirement")
    v["insurance_effective_at"] = eff
    v["insurance_expires_at"] = exp
    v["insurance_coverage_cents"] = cov
    touch(v)
    return resp_object(ser_vendor(v), 200)


@app.route("/vendors/<vid>/payments", methods=["POST"])
def create_payment(vid):
    uid, role = get_auth()
    authorize(role, {"Vendor"})
    if uid != vid:
        raise ApiError("ERR_OWNERSHIP", 403, "Vendor may only act on its own record")
    v = find("vendors", vid)
    body = get_body()
    amount = require_int(body, "amount_cents")
    balance = v["total_charged_cents"] - v["total_credited_cents"]
    if amount <= 0 or amount > balance:
        raise ApiError("ERR_PAYMENT_INVALID", 422, "Payment must be >0 and not exceed outstanding balance")
    credit(v, amount)
    return resp_object(ser_vendor(v), 200)


# ===========================================================================
# Commissary
# ===========================================================================
@app.route("/commissaries", methods=["POST"])
def create_commissary():
    _, role = get_auth()
    authorize(role, {"HealthInspector"})
    body = get_body()
    name = require_str(body, "name")
    grade = require_str(body, "health_grade")
    lic = require_datetime(body, "license_expires_at")
    check_enum(grade, HEALTH_GRADES, "health_grade")
    c = base_fields()
    c.update({
        "name": name,
        "health_grade": grade,
        "license_expires_at": lic,
        "status": "ACTIVE",
    })
    DB["commissaries"][c["id"]] = c
    return resp_object(ser_commissary(c), 201)


@app.route("/commissaries/<cid>", methods=["GET"])
def get_commissary(cid):
    _, role = get_auth()
    authorize(role, {"Vendor", "HealthInspector", "PermitOfficer"})
    c = find("commissaries", cid)
    return resp_object(ser_commissary(c), 200)


@app.route("/commissaries/<cid>", methods=["PATCH"])
def patch_commissary(cid):
    _, role = get_auth()
    authorize(role, {"HealthInspector"})
    c = find("commissaries", cid)
    body = get_body()
    if "status" in body and body["status"] is not None:
        st = body["status"]
        if not isinstance(st, str):
            raise ApiError("ERR_VALIDATION", 400, "status must be a string")
        check_enum(st, COMMISSARY_STATUS, "status")
        c["status"] = st
    if "license_expires_at" in body and body["license_expires_at"] is not None:
        lic = require_datetime(body, "license_expires_at")
        c["license_expires_at"] = lic
    touch(c)
    return resp_object(ser_commissary(c), 200)


# ===========================================================================
# Cart
# ===========================================================================
@app.route("/carts", methods=["POST"])
def create_cart():
    uid, role = get_auth()
    authorize(role, {"Vendor"})
    body = get_body()
    vendor_id = require_str(body, "vendor_id")
    if vendor_id != uid:
        raise ApiError("ERR_OWNERSHIP", 403, "Vendor may only register carts under its own id")
    commissary_id = require_str(body, "commissary_id")
    cart_type = require_str(body, "cart_type")
    size = require_int(body, "size_sqft")
    check_enum(cart_type, CART_TYPES, "cart_type")
    find("vendors", vendor_id)
    find("commissaries", commissary_id)
    c = base_fields()
    c.update({
        "vendor_id": vendor_id,
        "commissary_id": commissary_id,
        "cart_type": cart_type,
        "size_sqft": size,
        "_inspection_result": None,
        "inspection_score": None,
        "inspection_expires_at": None,
        "status": "PENDING",
    })
    DB["carts"][c["id"]] = c
    return resp_object(ser_cart(c), 201)


@app.route("/carts/<cid>", methods=["GET"])
def get_cart(cid):
    _, role = get_auth()
    authorize(role, {"Vendor", "PermitOfficer", "HealthInspector", "EnforcementOfficer"})
    c = find("carts", cid)
    return resp_object(ser_cart(c), 200)


@app.route("/carts", methods=["GET"])
def list_carts():
    _, role = get_auth()
    authorize(role, {"Vendor", "PermitOfficer", "HealthInspector", "EnforcementOfficer"})
    items = list(DB["carts"].values())
    for key in ("vendor_id", "commissary_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c[key] == val]
    return list_response(items, ser_cart)


@app.route("/carts/<cid>/inspect", methods=["POST"])
def inspect_cart(cid):
    _, role = get_auth()
    authorize(role, {"HealthInspector"})
    c = find("carts", cid)
    body = get_body()
    require_str(body, "inspection_type")
    result = require_str(body, "result")
    score = require_int(body, "score")
    check_enum(result, INSPECT_RESULTS, "result")
    exp = None
    if result == "PASS":
        exp = require_datetime(body, "inspection_expires_at")
    elif body.get("inspection_expires_at") is not None:
        exp = require_datetime(body, "inspection_expires_at")
    c["_inspection_result"] = result
    c["inspection_score"] = score
    c["inspection_expires_at"] = exp
    touch(c)
    if result == "FAIL":
        for p in DB["permits"].values():
            if p["cart_id"] == c["id"] and p["status"] == "ISSUED":
                suspend_permit_from_issued(p)
    return resp_object(ser_cart(c), 201)


@app.route("/carts/<cid>/approve", methods=["POST"])
def approve_cart(cid):
    _, role = get_auth()
    authorize(role, {"PermitOfficer"})
    c = find("carts", cid)
    if c["status"] == "RETIRED":
        raise ApiError("ERR_TERMINAL_STATE", 409, "Cart is retired")
    if c["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Cart must be PENDING to approve")
    # inspection: valid unexpired PASS
    passed = (c["_inspection_result"] == "PASS" and c["inspection_expires_at"] is not None
              and parse_iso(c["inspection_expires_at"]) > now())
    if not passed:
        raise ApiError("ERR_INSPECTION_NOT_PASSED", 422, "Cart requires a valid unexpired PASS inspection")
    comm = DB["commissaries"].get(c["commissary_id"])
    if comm is None or comm["status"] != "ACTIVE" or parse_iso(comm["license_expires_at"]) <= now():
        raise ApiError("ERR_COMMISSARY_NOT_ACTIVE", 422, "Commissary must be ACTIVE with unexpired license")
    c["status"] = "APPROVED"
    touch(c)
    return resp_object(ser_cart(c), 200)


# ===========================================================================
# Zone / Spot
# ===========================================================================
@app.route("/zones", methods=["POST"])
def create_zone():
    _, role = get_auth()
    authorize(role, {"PermitOfficer"})
    body = get_body()
    name = require_str(body, "name")
    zone_type = require_str(body, "zone_type")
    capacity = require_int(body, "capacity_slots")
    spacing = require_int(body, "spacing_min_feet")
    check_enum(zone_type, ZONE_TYPES, "zone_type")
    z = base_fields()
    z.update({
        "name": name,
        "zone_type": zone_type,
        "capacity_slots": capacity,
        "spacing_min_feet": spacing,
        "status": "OPEN",
    })
    DB["zones"][z["id"]] = z
    return resp_object(ser_zone(z), 201)


@app.route("/zones/<zid>", methods=["GET"])
def get_zone(zid):
    _, role = get_auth()
    authorize(role, {"Vendor", "PermitOfficer"})
    z = find("zones", zid)
    return resp_object(ser_zone(z), 200)


@app.route("/zones/<zid>/spots", methods=["POST"])
def create_spot(zid):
    _, role = get_auth()
    authorize(role, {"PermitOfficer"})
    z = find("zones", zid)
    body = get_body()
    label = require_str(body, "label")
    pos = require_int(body, "position_feet")
    s = base_fields()
    s.update({
        "zone_id": z["id"],
        "label": label,
        "position_feet": pos,
    })
    DB["spots"][s["id"]] = s
    return resp_object(ser_spot(s), 201)


@app.route("/zones/<zid>/spots", methods=["GET"])
def list_spots(zid):
    _, role = get_auth()
    authorize(role, {"Vendor", "PermitOfficer"})
    find("zones", zid)
    items = [s for s in DB["spots"].values() if s["zone_id"] == zid]
    val = request.args.get("status")
    if val is not None:
        items = [s for s in items if spot_status(s) == val]
    return list_response(items, ser_spot)


@app.route("/spots/<sid>", methods=["GET"])
def get_spot(sid):
    _, role = get_auth()
    authorize(role, {"Vendor", "PermitOfficer"})
    s = find("spots", sid)
    return resp_object(ser_spot(s), 200)


# ===========================================================================
# Permit
# ===========================================================================
@app.route("/permits", methods=["POST"])
def create_permit():
    uid, role = get_auth()
    authorize(role, {"Vendor"})
    body = get_body()
    vendor_id = require_str(body, "vendor_id")
    if vendor_id != uid:
        raise ApiError("ERR_OWNERSHIP", 403, "Vendor may only create permits under its own id")
    cart_id = require_str(body, "cart_id")
    zone_id = require_str(body, "zone_id")
    permit_type = require_str(body, "permit_type")
    check_enum(permit_type, PERMIT_TYPES, "permit_type")
    find("vendors", vendor_id)
    find("carts", cart_id)
    find("zones", zone_id)
    p = base_fields()
    p.update({
        "vendor_id": vendor_id,
        "cart_id": cart_id,
        "zone_id": zone_id,
        "permit_type": permit_type,
        "status": "DRAFT",
        "fee_variant": None,
        "fee_amount_cents": None,
        "issued_at": None,
        "expires_at": None,
    })
    DB["permits"][p["id"]] = p
    return resp_object(ser_permit(p), 201)


@app.route("/permits/<pid>", methods=["GET"])
def get_permit(pid):
    _, role = get_auth()
    authorize(role, {"Vendor", "PermitOfficer", "EnforcementOfficer"})
    p = find("permits", pid)
    return resp_object(ser_permit(p), 200)


@app.route("/permits", methods=["GET"])
def list_permits():
    _, role = get_auth()
    authorize(role, {"Vendor", "PermitOfficer", "EnforcementOfficer"})
    items = list(DB["permits"].values())
    for key in ("vendor_id", "cart_id", "zone_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p[key] == val]
    return list_response(items, ser_permit)


@app.route("/permits/<pid>/submit", methods=["POST"])
def submit_permit(pid):
    uid, role = get_auth()
    authorize(role, {"Vendor"})
    p = find("permits", pid)
    if p["vendor_id"] != uid:
        raise ApiError("ERR_OWNERSHIP", 403, "Vendor does not own this permit")
    if p["status"] == "REVOKED":
        raise ApiError("ERR_TERMINAL_STATE", 409, "Permit is revoked")
    if p["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Permit must be DRAFT to submit")
    p["status"] = "SUBMITTED"
    touch(p)
    return resp_object(ser_permit(p), 200)


@app.route("/permits/<pid>/issue", methods=["POST"])
def issue_permit(pid):
    _, role = get_auth()
    authorize(role, {"PermitOfficer"})
    p = find("permits", pid)
    if p["status"] == "REVOKED":
        raise ApiError("ERR_TERMINAL_STATE", 409, "Permit is revoked")
    if p["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Permit must be SUBMITTED to issue")
    vendor = DB["vendors"][p["vendor_id"]]
    cart = DB["carts"][p["cart_id"]]
    zone = DB["zones"][p["zone_id"]]
    if insurance_status(vendor) != "ACTIVE":
        raise ApiError("ERR_INSURANCE_NOT_ACTIVE", 422, "Vendor insurance not ACTIVE")
    if cart["status"] != "APPROVED":
        raise ApiError("ERR_CART_NOT_APPROVED", 409, "Cart must be APPROVED")
    prospective_start = now()
    prospective_end = now() + timedelta(days=PERMIT_TERM_DAYS)
    for other in DB["permits"].values():
        if other["id"] == p["id"] or other["cart_id"] != p["cart_id"]:
            continue
        if other["status"] != "ISSUED":
            continue
        o_issued = parse_iso(other["issued_at"])
        o_expires = parse_iso(other["expires_at"])
        if o_issued <= prospective_end and prospective_start <= o_expires:
            raise ApiError("ERR_PERMIT_OVERLAP", 409, "Overlapping ISSUED permit for this cart")
    fee = compute_permit_fee("NEW", zone, cart)
    p["fee_variant"] = "NEW"
    p["fee_amount_cents"] = fee
    p["issued_at"] = fmt_iso(now())
    p["expires_at"] = fmt_iso(now() + timedelta(days=PERMIT_TERM_DAYS))
    p["status"] = "ISSUED"
    touch(p)
    charge(vendor, fee)
    return resp_object(ser_permit(p), 200)


@app.route("/permits/<pid>/suspend", methods=["POST"])
def suspend_permit_endpoint(pid):
    _, role = get_auth()
    authorize(role, {"PermitOfficer", "EnforcementOfficer"})
    p = find("permits", pid)
    if p["status"] == "REVOKED":
        raise ApiError("ERR_TERMINAL_STATE", 409, "Permit is revoked")
    if p["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Permit must be ISSUED to suspend")
    suspend_permit_from_issued(p)
    return resp_object(ser_permit(p), 200)


@app.route("/permits/<pid>/reinstate", methods=["POST"])
def reinstate_permit(pid):
    _, role = get_auth()
    authorize(role, {"PermitOfficer"})
    p = find("permits", pid)
    if p["status"] == "REVOKED":
        raise ApiError("ERR_TERMINAL_STATE", 409, "Permit is revoked")
    if p["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Permit must be SUSPENDED to reinstate")
    if permit_violation_points(p) >= SUSPENSION_POINT_THRESHOLD:
        raise ApiError("ERR_INVALID_STATE", 409, "Violation points at or above suspension threshold")
    cart = DB["carts"][p["cart_id"]]
    if cart["status"] != "APPROVED":
        raise ApiError("ERR_CART_NOT_APPROVED", 409, "Cart must be APPROVED to reinstate")
    p["status"] = "ISSUED"
    touch(p)
    return resp_object(ser_permit(p), 200)


@app.route("/permits/<pid>/revoke", methods=["POST"])
def revoke_permit(pid):
    _, role = get_auth()
    authorize(role, {"PermitOfficer"})
    p = find("permits", pid)
    if p["status"] == "REVOKED":
        raise ApiError("ERR_TERMINAL_STATE", 409, "Permit is revoked")
    if p["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Permit must be SUSPENDED to revoke")
    p["status"] = "REVOKED"
    touch(p)
    return resp_object(ser_permit(p), 200)


@app.route("/permits/<pid>/renew", methods=["POST"])
def renew_permit(pid):
    uid, role = get_auth()
    authorize(role, {"Vendor"})
    p = find("permits", pid)
    if p["vendor_id"] != uid:
        raise ApiError("ERR_OWNERSHIP", 403, "Vendor does not own this permit")
    if p["status"] == "REVOKED":
        raise ApiError("ERR_TERMINAL_STATE", 409, "Permit is revoked")
    if p["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Permit must be ISSUED to renew")
    expires = parse_iso(p["expires_at"])
    grace_end = expires + timedelta(days=RENEWAL_GRACE_DAYS)
    if now() < expires:
        variant = "RENEWAL_EARLY"
    elif now() < grace_end:
        variant = "RENEWAL_LATE"
    else:
        raise ApiError("ERR_RENEWAL_WINDOW_CLOSED", 422, "Renewal window has closed")
    vendor = DB["vendors"][p["vendor_id"]]
    cart = DB["carts"][p["cart_id"]]
    zone = DB["zones"][p["zone_id"]]
    fee = compute_permit_fee(variant, zone, cart)
    p["fee_variant"] = variant
    p["fee_amount_cents"] = fee
    p["expires_at"] = fmt_iso(now() + timedelta(days=PERMIT_TERM_DAYS))
    touch(p)
    charge(vendor, fee)
    return resp_object(ser_permit(p), 200)


@app.route("/permits/<pid>/violations", methods=["POST"])
def create_violation(pid):
    uid, role = get_auth()
    authorize(role, {"EnforcementOfficer"})
    p = find("permits", pid)
    body = get_body()
    vtype = require_str(body, "violation_type")
    desc = require_str(body, "description")
    check_enum(vtype, VIOLATION_TYPES, "violation_type")
    vendor = DB["vendors"][p["vendor_id"]]
    v = base_fields()
    v.update({
        "permit_id": p["id"],
        "violation_type": vtype,
        "description": desc,
        "points": VIOLATION_POINTS[vtype],
        "fine_cents": VIOLATION_FINE_CENTS[vtype],
        "issuer_user_id": uid,
        "source_complaint_id": None,
        "status": "ISSUED",
    })
    DB["violations"][v["id"]] = v
    charge(vendor, v["fine_cents"])
    return resp_object(ser_violation(v), 201)


@app.route("/permits/<pid>/violations", methods=["GET"])
def list_violations(pid):
    _, role = get_auth()
    authorize(role, {"Vendor", "PermitOfficer", "EnforcementOfficer"})
    find("permits", pid)
    items = [v for v in DB["violations"].values() if v["permit_id"] == pid]
    val = request.args.get("status")
    if val is not None:
        items = [v for v in items if v["status"] == val]
    return list_response(items, ser_violation)


@app.route("/permits/<pid>/complaints", methods=["POST"])
def create_complaint(pid):
    _, role = get_auth()
    authorize(role, {"Resident", "Vendor"})
    p = find("permits", pid)
    body = get_body()
    ctype = require_str(body, "complaint_type")
    desc = require_str(body, "description")
    check_enum(ctype, COMPLAINT_TYPES, "complaint_type")
    c = base_fields()
    c.update({
        "permit_id": p["id"],
        "complaint_type": ctype,
        "description": desc,
        "resolution": None,
        "generated_violation_id": None,
        "status": "OPEN",
    })
    DB["complaints"][c["id"]] = c
    return resp_object(ser_complaint(c), 201)


@app.route("/permits/<pid>/complaints", methods=["GET"])
def list_complaints(pid):
    _, role = get_auth()
    authorize(role, {"Vendor", "PermitOfficer", "EnforcementOfficer"})
    find("permits", pid)
    items = [c for c in DB["complaints"].values() if c["permit_id"] == pid]
    val = request.args.get("status")
    if val is not None:
        items = [c for c in items if c["status"] == val]
    return list_response(items, ser_complaint)


# ===========================================================================
# Violation
# ===========================================================================
@app.route("/violations/<vid>", methods=["GET"])
def get_violation(vid):
    _, role = get_auth()
    authorize(role, {"Vendor", "PermitOfficer", "EnforcementOfficer"})
    v = find("violations", vid)
    return resp_object(ser_violation(v), 200)


@app.route("/violations/<vid>/contest", methods=["POST"])
def contest_violation(vid):
    uid, role = get_auth()
    authorize(role, {"Vendor"})
    v = find("violations", vid)
    p = DB["permits"][v["permit_id"]]
    if p["vendor_id"] != uid:
        raise ApiError("ERR_OWNERSHIP", 403, "Vendor does not own the cited permit")
    if v["status"] in ("UPHELD", "DISMISSED"):
        raise ApiError("ERR_TERMINAL_STATE", 409, "Violation is terminal")
    if v["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Violation must be ISSUED to contest")
    v["status"] = "CONTESTED"
    touch(v)
    return resp_object(ser_violation(v), 200)


@app.route("/violations/<vid>/withdraw-contest", methods=["POST"])
def withdraw_contest(vid):
    uid, role = get_auth()
    authorize(role, {"Vendor"})
    v = find("violations", vid)
    p = DB["permits"][v["permit_id"]]
    if p["vendor_id"] != uid:
        raise ApiError("ERR_OWNERSHIP", 403, "Vendor does not own the cited permit")
    if v["status"] in ("UPHELD", "DISMISSED"):
        raise ApiError("ERR_TERMINAL_STATE", 409, "Violation is terminal")
    if v["status"] != "CONTESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Violation must be CONTESTED to withdraw")
    v["status"] = "ISSUED"
    touch(v)
    return resp_object(ser_violation(v), 200)


@app.route("/violations/<vid>/adjudicate", methods=["POST"])
def adjudicate_violation(vid):
    uid, role = get_auth()
    authorize(role, {"EnforcementOfficer"})
    v = find("violations", vid)
    body = get_body()
    outcome = require_str(body, "outcome")
    check_enum(outcome, ADJ_OUTCOMES, "outcome")
    if v["status"] in ("UPHELD", "DISMISSED"):
        raise ApiError("ERR_TERMINAL_STATE", 409, "Violation is terminal")
    if v["status"] not in ("ISSUED", "CONTESTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Violation must be ISSUED or CONTESTED to adjudicate")
    if uid == v["issuer_user_id"]:
        raise ApiError("ERR_SELF_ADJUDICATION", 403, "Adjudicating officer must differ from citing officer")
    p = DB["permits"][v["permit_id"]]
    vendor = DB["vendors"][p["vendor_id"]]
    if outcome == "UPHOLD":
        v["status"] = "UPHELD"
        touch(v)
        if permit_violation_points(p) >= SUSPENSION_POINT_THRESHOLD and p["status"] == "ISSUED":
            suspend_permit_from_issued(p)
    else:
        v["status"] = "DISMISSED"
        touch(v)
        credit(vendor, v["fine_cents"])
    return resp_object(ser_violation(v), 200)


# ===========================================================================
# Impound (child of Cart)
# ===========================================================================
@app.route("/carts/<cid>/impounds", methods=["POST"])
def create_impound(cid):
    _, role = get_auth()
    authorize(role, {"EnforcementOfficer"})
    c = find("carts", cid)
    body = get_body()
    reason = require_str(body, "reason")
    impounded_at = require_datetime(body, "impounded_at")
    check_enum(reason, IMPOUND_REASONS, "reason")
    if c["status"] == "RETIRED":
        raise ApiError("ERR_TERMINAL_STATE", 409, "Cart is retired")
    if c["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Cart must be APPROVED to impound")
    i = base_fields()
    i.update({
        "cart_id": c["id"],
        "reason": reason,
        "impounded_at": impounded_at,
        "settled_at": None,
        "storage_days": None,
        "settlement_variant": None,
        "release_fee_cents": 0,
        "municipal_writeoff_cents": 0,
        "status": "HELD",
    })
    DB["impounds"][i["id"]] = i
    c["status"] = "IMPOUNDED"
    touch(c)
    for p in DB["permits"].values():
        if p["cart_id"] == c["id"] and p["status"] == "ISSUED":
            suspend_permit_from_issued(p)
    return resp_object(ser_impound(i), 201)


@app.route("/carts/<cid>/impounds", methods=["GET"])
def list_impounds(cid):
    _, role = get_auth()
    authorize(role, {"Vendor", "EnforcementOfficer", "PermitOfficer"})
    find("carts", cid)
    items = [i for i in DB["impounds"].values() if i["cart_id"] == cid]
    val = request.args.get("status")
    if val is not None:
        items = [i for i in items if i["status"] == val]
    return list_response(items, ser_impound)


@app.route("/impounds/<iid>", methods=["GET"])
def get_impound(iid):
    _, role = get_auth()
    authorize(role, {"Vendor", "EnforcementOfficer", "PermitOfficer"})
    i = find("impounds", iid)
    return resp_object(ser_impound(i), 200)


@app.route("/impounds/<iid>/release", methods=["POST"])
def release_impound(iid):
    _, role = get_auth()
    authorize(role, {"EnforcementOfficer"})
    i = find("impounds", iid)
    body = get_body()
    release_at = require_datetime(body, "release_at")
    if i["status"] in ("RELEASED", "FORFEITED"):
        raise ApiError("ERR_TERMINAL_STATE", 409, "Impound already settled")
    if i["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE", 409, "Impound must be HELD to release")
    days = compute_storage_days(i["impounded_at"], release_at)
    storage = compute_storage_cost(days)
    fee = IMPOUND_BASE_FEE_CENTS + storage + IMPOUND_ADMIN_FEE_CENTS
    i["settled_at"] = release_at
    i["storage_days"] = days
    i["settlement_variant"] = "RELEASE"
    i["release_fee_cents"] = fee
    i["municipal_writeoff_cents"] = 0
    i["status"] = "RELEASED"
    touch(i)
    cart = DB["carts"][i["cart_id"]]
    vendor = DB["vendors"][cart["vendor_id"]]
    charge(vendor, fee)
    cart["status"] = "APPROVED"
    touch(cart)
    return resp_object(ser_impound(i), 200)


@app.route("/impounds/<iid>/forfeit", methods=["POST"])
def forfeit_impound(iid):
    _, role = get_auth()
    authorize(role, {"EnforcementOfficer"})
    i = find("impounds", iid)
    body = get_body()
    forfeit_at = require_datetime(body, "forfeit_at")
    if i["status"] in ("RELEASED", "FORFEITED"):
        raise ApiError("ERR_TERMINAL_STATE", 409, "Impound already settled")
    if i["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE", 409, "Impound must be HELD to forfeit")
    days = compute_storage_days(i["impounded_at"], forfeit_at)
    storage = compute_storage_cost(days)
    writeoff = IMPOUND_BASE_FEE_CENTS + storage
    i["settled_at"] = forfeit_at
    i["storage_days"] = days
    i["settlement_variant"] = "FORFEITURE"
    i["release_fee_cents"] = 0
    i["municipal_writeoff_cents"] = writeoff
    i["status"] = "FORFEITED"
    touch(i)
    cart = DB["carts"][i["cart_id"]]
    cart["status"] = "RETIRED"
    touch(cart)
    return resp_object(ser_impound(i), 200)


# ===========================================================================
# Complaint
# ===========================================================================
@app.route("/complaints/<cid>", methods=["GET"])
def get_complaint(cid):
    _, role = get_auth()
    authorize(role, {"Vendor", "Resident", "PermitOfficer", "EnforcementOfficer"})
    c = find("complaints", cid)
    return resp_object(ser_complaint(c), 200)


@app.route("/complaints/<cid>/resolve", methods=["POST"])
def resolve_complaint(cid):
    uid, role = get_auth()
    authorize(role, {"EnforcementOfficer"})
    c = find("complaints", cid)
    body = get_body()
    outcome = require_str(body, "resolution_outcome")
    check_enum(outcome, RESOLUTION_OUTCOMES, "resolution_outcome")
    resolution = None
    if body.get("resolution") is not None:
        resolution = require_str(body, "resolution")
    if c["status"] in ("SUBSTANTIATED", "UNFOUNDED"):
        raise ApiError("ERR_TERMINAL_STATE", 409, "Complaint already resolved")
    if c["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Complaint must be OPEN to resolve")
    c["resolution"] = resolution
    if outcome == "UNFOUNDED":
        c["status"] = "UNFOUNDED"
        touch(c)
        return resp_object(ser_complaint(c), 200)
    # SUBSTANTIATED: auto-create a MAJOR violation, immediately UPHELD
    p = DB["permits"][c["permit_id"]]
    v = base_fields()
    v.update({
        "permit_id": p["id"],
        "violation_type": "MAJOR",
        "description": "Auto-generated from substantiated complaint %s" % c["id"],
        "points": VIOLATION_POINTS["MAJOR"],
        "fine_cents": VIOLATION_FINE_CENTS["MAJOR"],
        "issuer_user_id": None,
        "source_complaint_id": c["id"],
        "status": "UPHELD",
    })
    DB["violations"][v["id"]] = v
    c["generated_violation_id"] = v["id"]
    c["status"] = "SUBSTANTIATED"
    touch(c)
    if permit_violation_points(p) >= SUSPENSION_POINT_THRESHOLD and p["status"] == "ISSUED":
        suspend_permit_from_issued(p)
    return resp_object(ser_complaint(c), 200)


# ===========================================================================
# Lottery
# ===========================================================================
@app.route("/lotteries", methods=["POST"])
def create_lottery():
    _, role = get_auth()
    authorize(role, {"PermitOfficer"})
    body = get_body()
    zone_id = require_str(body, "zone_id")
    entry_fee = require_int(body, "entry_fee_cents")
    term_start = require_datetime(body, "term_start_at")
    term_end = require_datetime(body, "term_end_at")
    find("zones", zone_id)
    l = base_fields()
    l.update({
        "zone_id": zone_id,
        "entry_fee_cents": entry_fee,
        "term_start_at": term_start,
        "term_end_at": term_end,
        "status": "OPEN",
    })
    DB["lotteries"][l["id"]] = l
    return resp_object(ser_lottery(l), 201)


@app.route("/lotteries/<lid>", methods=["GET"])
def get_lottery(lid):
    _, role = get_auth()
    authorize(role, {"Vendor", "PermitOfficer"})
    l = find("lotteries", lid)
    return resp_object(ser_lottery(l), 200)


@app.route("/lotteries", methods=["GET"])
def list_lotteries():
    _, role = get_auth()
    authorize(role, {"Vendor", "PermitOfficer"})
    items = list(DB["lotteries"].values())
    for key in ("zone_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [l for l in items if l[key] == val]
    return list_response(items, ser_lottery)


@app.route("/lotteries/<lid>/entries", methods=["POST"])
def create_entry(lid):
    uid, role = get_auth()
    authorize(role, {"Vendor"})
    l = find("lotteries", lid)
    body = get_body()
    permit_id = require_str(body, "permit_id")
    if "preferred_spot_ids" not in body or body["preferred_spot_ids"] is None:
        raise ApiError("ERR_VALIDATION", 400, "Missing required field: preferred_spot_ids")
    preferred = body["preferred_spot_ids"]
    if not isinstance(preferred, list) or not all(isinstance(x, str) for x in preferred):
        raise ApiError("ERR_VALIDATION", 400, "preferred_spot_ids must be a list of strings")
    p = find("permits", permit_id)
    if p["vendor_id"] != uid:
        raise ApiError("ERR_OWNERSHIP", 403, "Vendor does not own this permit")
    if p["status"] != "ISSUED":
        raise ApiError("ERR_NOT_ELIGIBLE_LOTTERY", 422, "Lottery entry requires an ISSUED permit")
    vendor = DB["vendors"][p["vendor_id"]]
    e = base_fields()
    e.update({
        "lottery_id": l["id"],
        "permit_id": permit_id,
        "preferred_spot_ids": list(preferred),
        "rank_score": None,
        "awarded_spot_id": None,
        "status": "ENTERED",
    })
    DB["lottery_entries"][e["id"]] = e
    charge(vendor, l["entry_fee_cents"])
    return resp_object(ser_entry(e), 201)


@app.route("/lotteries/<lid>/draw", methods=["POST"])
def draw_lottery(lid):
    _, role = get_auth()
    authorize(role, {"PermitOfficer"})
    l = find("lotteries", lid)
    if l["status"] == "DRAWN":
        raise ApiError("ERR_LOTTERY_NOT_OPEN", 409, "Lottery is not OPEN")
    if l["status"] != "OPEN":
        raise ApiError("ERR_LOTTERY_NOT_OPEN", 409, "Lottery is not OPEN")
    zone = DB["zones"][l["zone_id"]]
    if zone["status"] != "OPEN":
        raise ApiError("ERR_ZONE_CLOSED", 409, "Lottery zone is not OPEN")

    entries = [e for e in DB["lottery_entries"].values()
               if e["lottery_id"] == l["id"] and e["status"] == "ENTERED"]

    eligible = []
    ineligible = []
    for e in entries:
        p = DB["permits"][e["permit_id"]]
        vendor = DB["vendors"][p["vendor_id"]]
        held = any(
            imp["status"] == "HELD" and DB["carts"][imp["cart_id"]]["vendor_id"] == vendor["id"]
            for imp in DB["impounds"].values()
            if imp["cart_id"] in DB["carts"]
        )
        if p["status"] != "ISSUED" or held:
            ineligible.append(e)
        else:
            score = (vendor["seniority_years"] * LOTTERY_W_SENIORITY
                     + compliance_score(vendor) * LOTTERY_W_COMPLIANCE
                     - permit_violation_points(p) * LOTTERY_W_VIOLATION)
            e["rank_score"] = score
            eligible.append(e)

    eligible.sort(key=lambda e: (-e["rank_score"], e["_seq"]))

    for e in eligible:
        assigned = zone_assigned_slots(zone)
        available = zone["capacity_slots"] - assigned
        if available <= 0:
            e["status"] = "WAITLISTED"
            touch(e)
            continue
        awarded_spot = None
        for sid in e["preferred_spot_ids"]:
            spot = DB["spots"].get(sid)
            if spot is None or spot["zone_id"] != zone["id"]:
                continue
            if spot_status(spot) == "AVAILABLE":
                awarded_spot = spot
                break
        if awarded_spot is None:
            e["status"] = "WAITLISTED"
            touch(e)
            continue
        e["status"] = "AWARDED"
        e["awarded_spot_id"] = awarded_spot["id"]
        touch(e)
        a = base_fields()
        a.update({
            "spot_id": awarded_spot["id"],
            "permit_id": e["permit_id"],
            "zone_id": zone["id"],
            "position_feet": awarded_spot["position_feet"],
            "start_at": l["term_start_at"],
            "end_at": l["term_end_at"],
            "origin": "LOTTERY",
            "status": "ACTIVE",
        })
        DB["spot_assignments"][a["id"]] = a
        touch(zone)  # bump zone.version

    for e in ineligible:
        e["status"] = "WAITLISTED"
        touch(e)

    l["status"] = "DRAWN"
    touch(l)
    return resp_object(ser_lottery(l), 200)


@app.route("/lottery-entries/<eid>", methods=["GET"])
def get_entry(eid):
    _, role = get_auth()
    authorize(role, {"Vendor", "PermitOfficer"})
    e = find("lottery_entries", eid)
    return resp_object(ser_entry(e), 200)


@app.route("/lottery-entries", methods=["GET"])
def list_entries():
    _, role = get_auth()
    authorize(role, {"Vendor", "PermitOfficer"})
    items = list(DB["lottery_entries"].values())
    for key in ("lottery_id", "permit_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e[key] == val]
    return list_response(items, ser_entry)


# ===========================================================================
# SpotAssignment
# ===========================================================================
def windows_overlap(s1, e1, s2, e2):
    # half-open [s,e): overlap iff s1 < e2 and s2 < e1
    return s1 < e2 and s2 < e1


@app.route("/permits/<pid>/spot-assignments", methods=["POST"])
def create_assignment(pid):
    _, role = get_auth()
    authorize(role, {"PermitOfficer"})
    p = find("permits", pid)
    body = get_body()
    spot_id = require_str(body, "spot_id")
    start_at = require_datetime(body, "start_at")
    end_at = require_datetime(body, "end_at")
    expected_version = require_int(body, "expected_zone_version")
    spot = find("spots", spot_id)
    zone = DB["zones"][spot["zone_id"]]

    new_start = parse_iso(start_at)
    new_end = parse_iso(end_at)
    new_pos = spot["position_feet"]

    # (1) time conflict on the same spot
    for a in DB["spot_assignments"].values():
        if a["status"] != "ACTIVE" or a["spot_id"] != spot_id:
            continue
        if windows_overlap(new_start, new_end, parse_iso(a["start_at"]), parse_iso(a["end_at"])):
            raise ApiError("ERR_SPOT_TIME_CONFLICT", 409, "Time window conflicts with an active assignment")

    # (2) spacing across the zone
    for a in DB["spot_assignments"].values():
        if a["status"] != "ACTIVE" or a["zone_id"] != zone["id"]:
            continue
        if abs(new_pos - a["position_feet"]) < zone["spacing_min_feet"] and \
                windows_overlap(new_start, new_end, parse_iso(a["start_at"]), parse_iso(a["end_at"])):
            raise ApiError("ERR_SPACING_VIOLATION", 409, "Spacing buffer violated")

    # (3) zone availability
    assigned = zone_assigned_slots(zone)
    if zone["capacity_slots"] - assigned <= 0:
        raise ApiError("ERR_ZONE_CAPACITY_FULL", 409, "Zone has no available slots")
    if zone["status"] == "CLOSED":
        raise ApiError("ERR_ZONE_CLOSED", 409, "Zone is CLOSED")

    # (4) OCC stale version
    if expected_version != zone["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_zone_version does not match zone version")

    a = base_fields()
    a.update({
        "spot_id": spot_id,
        "permit_id": p["id"],
        "zone_id": zone["id"],
        "position_feet": spot["position_feet"],
        "start_at": start_at,
        "end_at": end_at,
        "origin": "DIRECT",
        "status": "ACTIVE",
    })
    DB["spot_assignments"][a["id"]] = a
    touch(zone)  # bump zone.version
    return resp_object(ser_assignment(a), 201)


@app.route("/spot-assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    _, role = get_auth()
    authorize(role, {"Vendor", "PermitOfficer"})
    a = find("spot_assignments", aid)
    return resp_object(ser_assignment(a), 200)


@app.route("/spot-assignments", methods=["GET"])
def list_assignments():
    _, role = get_auth()
    authorize(role, {"Vendor", "PermitOfficer"})
    items = list(DB["spot_assignments"].values())
    for key in ("spot_id", "permit_id", "zone_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a[key] == val]
    return list_response(items, ser_assignment)


@app.route("/spot-assignments/<aid>/release", methods=["POST"])
def release_assignment_endpoint(aid):
    uid, role = get_auth()
    authorize(role, {"PermitOfficer", "Vendor"})
    a = find("spot_assignments", aid)
    if role == "Vendor":
        p = DB["permits"][a["permit_id"]]
        if p["vendor_id"] != uid:
            raise ApiError("ERR_OWNERSHIP", 403, "Vendor does not own this assignment")
    if a["status"] == "RELEASED":
        raise ApiError("ERR_TERMINAL_STATE", 409, "Assignment already released")
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Assignment must be ACTIVE to release")
    release_assignment(a)
    return resp_object(ser_assignment(a), 200)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
