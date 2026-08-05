"""Off-Campus Student-Housing Marketplace API — Python + Flask, in-memory."""
import os
import re
import uuid
import string
import random
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD.constants)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

MIN_LEASE_TERM_DAYS = 90
MAX_LEASE_TERM_DAYS = 400
TURNOVER_BUFFER_DAYS = 14
DAYS_PER_YEAR = 365
QUOTE_MONTH_DAYS = 30

MIN_INSTALLMENT_COUNT = 1
MAX_INSTALLMENT_COUNT = 12
INSTALLMENT_INTERVAL_DAYS = 30
LATE_GRACE_DAYS = 5
LATE_FEE_BPS = 500
LATE_FEE_CAP_CENTS = 7500

PARTNER_DISCOUNT_BPS_PREFERRED = 500
PARTNER_DISCOUNT_BPS_STANDARD = 0
VERIFICATION_TOKEN_TTL_DAYS = 14

GUARANTOR_RENT_THRESHOLD_CENTS = 120000
GUARANTOR_MIN_INCOME_MULTIPLE_BPS = 30000
GUARANTOR_MAX_REVIEW_ROUNDS = 3

MATCH_SCORE_MAX = 100
MATCH_SCORE_MIN = 0
MATCH_CLEANLINESS_WEIGHT = 12
MATCH_NOISE_WEIGHT = 8
MATCH_SLEEP_PENALTY = 25
MATCH_SMOKER_PENALTY = 30
GROUP_MIN_AVG_MATCH_SCORE = 55
GROUP_MIN_SIZE = 2
GROUP_MAX_SIZE = 8

SUBLET_MIN_TERM_DAYS = 21
SUBLET_MAX_MARKUP_BPS = 11000
SUBLET_FEE_BPS = 800
SUBLET_MIN_FEE_CENTS = 2500

AMENITY_MIN_TERM_DAYS = 30

PAYOUT_TIER1_MAX_CENTS = 500000
PAYOUT_TIER2_MAX_CENTS = 2000000
PAYOUT_TIER1_BPS = 900
PAYOUT_TIER2_BPS = 700
PAYOUT_TIER3_BPS = 500
MAINTENANCE_HOLDBACK_BPS = 200
PAYOUT_REBATE_MIN_SUBTOTAL_CENTS = 150000
PAYOUT_REBATE_PCT_BPS = 1000
PAYOUT_MIN_BALANCE_CENTS = 50000

ROLES = {"PlatformAdmin", "PropertyManager", "UniversityPartner", "Student"}
HOLDING = {"PENDING_GUARANTOR", "PENDING_SIGNATURE", "ACTIVE"}

# ---------------------------------------------------------------------------
# Error catalogue
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_VALIDATION": 400,
    "ERR_UNIVERSITY_NOT_FOUND": 404,
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_STUDENT_NOT_FOUND": 404,
    "ERR_GROUP_NOT_FOUND": 404,
    "ERR_MEMBERSHIP_NOT_FOUND": 404,
    "ERR_LEASE_NOT_FOUND": 404,
    "ERR_GUARANTOR_APPLICATION_NOT_FOUND": 404,
    "ERR_INSTALLMENT_NOT_FOUND": 404,
    "ERR_SUBLET_NOT_FOUND": 404,
    "ERR_AMENITY_NOT_FOUND": 404,
    "ERR_AMENITY_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_PAYOUT_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_PROPERTY_INVALID_STATE": 409,
    "ERR_STUDENT_INVALID_STATE": 409,
    "ERR_GROUP_INVALID_STATE": 409,
    "ERR_MEMBERSHIP_INVALID_STATE": 409,
    "ERR_LEASE_INVALID_STATE": 409,
    "ERR_GUARANTOR_INVALID_STATE": 409,
    "ERR_INSTALLMENT_NOT_PAYABLE": 409,
    "ERR_SUBLET_INVALID_STATE": 409,
    "ERR_ASSIGNMENT_INVALID_STATE": 409,
    "ERR_PAYOUT_INVALID_STATE": 409,
    "ERR_PROPERTY_NOT_ACTIVE": 409,
    "ERR_LEASE_NOT_ACTIVE": 409,
    "ERR_STUDENT_NOT_VERIFIED": 422,
    "ERR_BED_LABEL_UNKNOWN": 422,
    "ERR_AMENITY_PROPERTY_MISMATCH": 409,
    "ERR_UNIT_PROPERTY_MISMATCH": 409,
    "ERR_DUPLICATE_MEMBERSHIP": 409,
    "ERR_SUBTENANT_IS_LEASEHOLDER": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_VERIFICATION_EXPIRED": 422,
    "ERR_GUARANTOR_MAX_ROUNDS_EXCEEDED": 409,
    "ERR_GUARANTOR_NOT_REQUIRED": 409,
    "ERR_CLOCK_BACKWARDS": 422,
    "ERR_TERM_LENGTH_INVALID": 422,
    "ERR_TERM_START_IN_PAST": 422,
    "ERR_WINDOW_OUTSIDE_LEASE_TERM": 422,
    "ERR_WINDOW_TOO_SHORT": 422,
    "ERR_BED_TURNOVER_CONFLICT": 409,
    "ERR_SUBLET_OVERLAP": 409,
    "ERR_AMENITY_CAPACITY_EXCEEDED": 409,
    "ERR_PAYOUT_PERIOD_OVERLAP": 409,
    "ERR_UNIVERSITY_CODE_TAKEN": 409,
    "ERR_EMAIL_TAKEN": 409,
    "ERR_DUPLICATE_UNIT_NUMBER": 409,
    "ERR_BED_LABELS_MISMATCH": 422,
    "ERR_PROPERTY_HAS_NO_UNITS": 409,
    "ERR_GROUP_SIZE_MISMATCH": 409,
    "ERR_GROUP_MATCH_SCORE_TOO_LOW": 422,
    "ERR_UNIT_CAPACITY_INSUFFICIENT": 409,
    "ERR_GUARANTOR_INCOME_INSUFFICIENT": 422,
    "ERR_SUBLET_RENT_ABOVE_CAP": 422,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
    "ERR_PAYOUT_EMPTY_PERIOD": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


def err(error_id, message=""):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
DB = {
    "universities": {},
    "properties": {},
    "units": {},
    "students": {},
    "roommate_groups": {},
    "group_memberships": {},
    "leases": {},
    "guarantor_applications": {},
    "installments": {},
    "sublets": {},
    "amenities": {},
    "amenity_assignments": {},
    "payouts": {},
}
_SEQ = {"n": 0}
CLOCK = {"dt": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def now_wall():
    return datetime.now(timezone.utc)


def render_wall(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def render_logical(dt):
    # System datetime fields (logical-clock echoes: current_utc, *_at) render with
    # three fractional digits, matching the PRD's ISO 8601 rendering convention
    # (§2.3 api_request_timestamp, §2.4 created_at/updated_at). No input-format echo.
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_now():
    return CLOCK["dt"]


def clock_date():
    return CLOCK["dt"].date()


def clock_stamp():
    """Logical-clock instant rendered for a system datetime field."""
    return render_logical(CLOCK["dt"])


def new_id():
    return str(uuid.uuid4())


def make_entity(**fields):
    ts = render_wall(now_wall())
    base = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    base.update(fields)
    return base


def touch(ent):
    ent["version"] += 1
    ent["updated_at"] = render_wall(now_wall())


def public(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Numeric / date helpers
# ---------------------------------------------------------------------------
def round_half_up(numerator, denominator):
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def floor_div(a, b):
    return a // b


def ceil_div(a, b):
    return -((-a) // b)


def parse_date(s):
    if not isinstance(s, str):
        raise ValueError("not a date string")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        raise ValueError("bad date")
    return datetime.strptime(s, "%Y-%m-%d").date()


def parse_instant(s):
    if not isinstance(s, str):
        raise ValueError("not an instant string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def date_diff_days(end_d, start_d):
    return (end_d - start_d).days


def add_days(d, n):
    return d + timedelta(days=n)


# ---------------------------------------------------------------------------
# Envelope + response helpers
# ---------------------------------------------------------------------------
def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": render_wall(now_wall()),
    }


def respond_object(data, status=200):
    body = {"meta": meta_base(), "response_type": "object", "data": data}
    return jsonify(body), status


def respond_array(items, limit, offset, total_count, status=200):
    meta = meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    meta = meta_base()
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    meta = meta_base()
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "No such route."}}
    return jsonify(body), 400


@app.errorhandler(405)
def handle_405(e):
    meta = meta_base()
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed."}}
    return jsonify(body), 400


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    if role not in allowed_roles:
        err("ERR_UNAUTHORIZED", "Role not permitted for this endpoint.")
    return uid, role


def get_body():
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        return {}
    return body


# ---------------------------------------------------------------------------
# Field validation helpers (schema priority 6)
# ---------------------------------------------------------------------------
def require_present(body, field):
    if field not in body or body[field] is None:
        err("ERR_VALIDATION", f"Missing required field: {field}")
    return body[field]


def require_str(body, field):
    v = require_present(body, field)
    if not isinstance(v, str) or v == "":
        err("ERR_VALIDATION", f"Field {field} must be a non-empty string.")
    return v


def require_int(body, field, minimum=None, maximum=None):
    v = require_present(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_VALIDATION", f"Field {field} must be an integer.")
    if minimum is not None and v < minimum:
        err("ERR_VALIDATION", f"Field {field} below minimum {minimum}.")
    if maximum is not None and v > maximum:
        err("ERR_VALIDATION", f"Field {field} above maximum {maximum}.")
    return v


def require_enum(body, field, allowed):
    v = require_present(body, field)
    if v not in allowed:
        err("ERR_VALIDATION", f"Field {field} must be one of {sorted(allowed)}.")
    return v


def optional_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if v not in allowed:
        err("ERR_VALIDATION", f"Field {field} must be one of {sorted(allowed)}.")
    return v


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        err("ERR_VALIDATION", f"Field {field} must be a boolean.")
    return v


def require_date(body, field):
    v = require_present(body, field)
    try:
        return parse_date(v)
    except Exception:
        err("ERR_VALIDATION", f"Field {field} must be an ISO calendar date (YYYY-MM-DD).")


def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except Exception:
            err("ERR_VALIDATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            err("ERR_VALIDATION", "limit must be within 1..100.")
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except Exception:
            err("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            err("ERR_VALIDATION", "offset must be >= 0.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    return [public(r) for r in window], total


# ---------------------------------------------------------------------------
# Lookup helpers (existence — priority 3/4)
# ---------------------------------------------------------------------------
def _get(coll, ident, error_id):
    ent = DB[coll].get(ident)
    if ent is None:
        err(error_id)
    return ent


def get_university(i): return _get("universities", i, "ERR_UNIVERSITY_NOT_FOUND")
def get_property(i): return _get("properties", i, "ERR_PROPERTY_NOT_FOUND")
def get_unit(i): return _get("units", i, "ERR_UNIT_NOT_FOUND")
def get_student(i): return _get("students", i, "ERR_STUDENT_NOT_FOUND")
def get_group(i): return _get("roommate_groups", i, "ERR_GROUP_NOT_FOUND")
def get_membership(i): return _get("group_memberships", i, "ERR_MEMBERSHIP_NOT_FOUND")
def get_lease(i): return _get("leases", i, "ERR_LEASE_NOT_FOUND")
def get_guarantor(i): return _get("guarantor_applications", i, "ERR_GUARANTOR_APPLICATION_NOT_FOUND")
def get_installment(i): return _get("installments", i, "ERR_INSTALLMENT_NOT_FOUND")
def get_sublet(i): return _get("sublets", i, "ERR_SUBLET_NOT_FOUND")
def get_amenity(i): return _get("amenities", i, "ERR_AMENITY_NOT_FOUND")
def get_assignment(i): return _get("amenity_assignments", i, "ERR_AMENITY_ASSIGNMENT_NOT_FOUND")
def get_payout(i): return _get("payouts", i, "ERR_PAYOUT_NOT_FOUND")


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def pair_score(a, b):
    s = (MATCH_SCORE_MAX
         - MATCH_CLEANLINESS_WEIGHT * abs(a["cleanliness_level"] - b["cleanliness_level"])
         - MATCH_NOISE_WEIGHT * abs(a["noise_tolerance"] - b["noise_tolerance"])
         - (MATCH_SLEEP_PENALTY if a["sleep_schedule"] != b["sleep_schedule"] else 0)
         - (MATCH_SMOKER_PENALTY if a["smoker"] != b["smoker"] else 0))
    if s < MATCH_SCORE_MIN:
        s = MATCH_SCORE_MIN
    if s > MATCH_SCORE_MAX:
        s = MATCH_SCORE_MAX
    return s


def guarantor_income_multiple_bps(income_cents, monthly_rent_cents):
    annual = monthly_rent_cents * 12
    return floor_div(income_cents * 10000, annual)


def lease_guarantor_required(student, monthly_rent_cents):
    return (student["credit_score_band"] in ("THIN", "LOW")
            or monthly_rent_cents > GUARANTOR_RENT_THRESHOLD_CENTS)


# ---------------------------------------------------------------------------
# Rollups & cascades
# ---------------------------------------------------------------------------
def units_of_property(pid):
    return [u for u in DB["units"].values() if u["property_id"] == pid]


def leases_of_unit(uid):
    return [l for l in DB["leases"].values() if l["unit_id"] == uid]


def installments_of_lease(lid):
    return [i for i in DB["installments"].values() if i["lease_id"] == lid]


def recompute_unit_rollup(unit):
    holding = [l for l in leases_of_unit(unit["id"]) if l["lease_status"] in HOLDING]
    leased = len(holding)
    n = len(unit["bed_labels"])
    avail = n - leased
    if avail == 0:
        status = "FULLY_LEASED"
    elif leased == 0:
        status = "AVAILABLE"
    else:
        status = "PARTIALLY_LEASED"
    changed = (unit["leased_bed_count"] != leased
               or unit["available_bed_count"] != avail
               or unit["occupancy_status"] != status)
    unit["leased_bed_count"] = leased
    unit["available_bed_count"] = avail
    unit["occupancy_status"] = status
    if changed:
        touch(unit)


def recompute_property_rollup(prop):
    units = units_of_property(prop["id"])
    unit_count = len(units)
    total_bed = sum(len(u["bed_labels"]) for u in units)
    avail = sum(u["available_bed_count"] for u in units)
    changed = (prop["unit_count"] != unit_count
               or prop["total_bed_count"] != total_bed
               or prop["available_bed_count"] != avail)
    prop["unit_count"] = unit_count
    prop["total_bed_count"] = total_bed
    prop["available_bed_count"] = avail
    # auto-posture
    if prop["status"] == "LISTED" and avail == 0:
        prop["status"] = "FULLY_COMMITTED"
        changed = True
    elif prop["status"] == "FULLY_COMMITTED" and avail > 0:
        prop["status"] = "LISTED"
        changed = True
    if changed:
        touch(prop)


def recompute_escrow(prop):
    collected = 0
    prop_lease_ids = {l["id"] for l in DB["leases"].values() if l["property_id"] == prop["id"]}
    for i in DB["installments"].values():
        if i["status"] == "PAID" and i["lease_id"] in prop_lease_ids:
            collected += i["amount_cents"] + i["late_fee_cents"]
    disbursed = 0
    reserve = 0
    for p in DB["payouts"].values():
        if p["property_id"] == prop["id"] and p["status"] == "PAID":
            disbursed += p["gross_collected_cents"]
            reserve += p["holdback_cents"]
    escrow = collected - disbursed
    eligible = escrow >= PAYOUT_MIN_BALANCE_CENTS
    changed = (prop["escrow_balance_cents"] != escrow
               or prop["maintenance_reserve_cents"] != reserve
               or prop["payout_eligible"] != eligible)
    prop["escrow_balance_cents"] = escrow
    prop["maintenance_reserve_cents"] = reserve
    prop["payout_eligible"] = eligible
    if changed:
        touch(prop)


def recompute_lease_funding(lease):
    nv = [i for i in installments_of_lease(lease["id"]) if i["status"] != "VOID"]
    paid = [i for i in nv if i["status"] == "PAID"]
    lease["paid_cents"] = sum(i["amount_cents"] + i["late_fee_cents"] for i in paid)
    lease["amenity_fee_total_cents"] = sum(
        i["amount_cents"] for i in nv if i["kind"] in ("AMENITY", "SUBLET_FEE"))
    lease["billed_total_cents"] = (lease["total_contract_cents"] or 0) + lease["amenity_fee_total_cents"]
    cd = clock_date()
    if len(nv) == 0:
        status = "UNFUNDED"
    elif all(i["status"] == "PAID" for i in nv):
        status = "SETTLED"
    elif any(i["status"] == "LATE" for i in nv):
        status = "DELINQUENT"
    elif not any(i["status"] == "PAID" for i in nv):
        status = "UNFUNDED"
    elif all(i["status"] == "PAID" for i in nv if parse_date(i["due_date"]) <= cd):
        status = "CURRENT"
    else:
        status = "PARTIAL"
    lease["funding_status"] = status


def bed_slot_conflict(unit_id, bed_label, term_start, term_end, exclude_lease_id=None):
    ts = term_start if isinstance(term_start, date) else parse_date(term_start)
    te = term_end if isinstance(term_end, date) else parse_date(term_end)
    for l in DB["leases"].values():
        if l["unit_id"] != unit_id or l["bed_label"] != bed_label:
            continue
        if l["lease_status"] not in HOLDING:
            continue
        if exclude_lease_id and l["id"] == exclude_lease_id:
            continue
        e_start = parse_date(l["term_start_date"])
        e_end = parse_date(l["term_end_date"])
        if ts < add_days(e_end, TURNOVER_BUFFER_DAYS) and e_start < add_days(te, TURNOVER_BUFFER_DAYS):
            return True
    return False


def release_bed(lease):
    """After lease left a bed-holding state, recompute unit + property rollups."""
    unit = DB["units"].get(lease["unit_id"])
    if unit is None:
        return
    recompute_unit_rollup(unit)
    prop = DB["properties"].get(unit["property_id"])
    if prop is not None:
        recompute_property_rollup(prop)


def reserve_bed(lease):
    unit = DB["units"].get(lease["unit_id"])
    if unit is None:
        return
    recompute_unit_rollup(unit)
    prop = DB["properties"].get(unit["property_id"])
    if prop is not None:
        recompute_property_rollup(prop)


def property_of_lease(lease):
    return DB["properties"].get(lease["property_id"])


# ---------------------------------------------------------------------------
# Ownership helpers (priority 5)
# ---------------------------------------------------------------------------
def require_manager_owns_property(uid, prop):
    if prop["manager_user_id"] != uid:
        err("ERR_NOT_RESOURCE_OWNER", "Caller is not the property manager.")


def require_student_owns(uid, student_id):
    if uid != student_id:
        err("ERR_NOT_RESOURCE_OWNER", "Caller does not own this resource.")


# ---------------------------------------------------------------------------
# Generic list helper
# ---------------------------------------------------------------------------
def list_rows(coll, filter_fields, sort_key=None):
    rows = list(DB[coll].values())
    for f in filter_fields:
        val = request.args.get(f)
        if val is not None and val != "":
            rows = [r for r in rows if str(r.get(f)) == val]
    rows.sort(key=sort_key if sort_key else (lambda r: r["_seq"]))
    return rows


# ===========================================================================
# CLOCK
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    authenticate({"PlatformAdmin"})
    body = get_body()
    raw = require_present(body, "to_iso8601")
    try:
        new_dt = parse_instant(raw)
    except Exception:
        err("ERR_VALIDATION", "to_iso8601 must be a valid ISO 8601 instant.")
    if new_dt < CLOCK["dt"]:
        err("ERR_CLOCK_BACKWARDS", "Cannot move the logical clock backwards.")
    CLOCK["dt"] = new_dt
    cd = new_dt.date()

    late_count = 0
    affected_leases = set()
    for i in DB["installments"].values():
        if i["status"] != "SCHEDULED":
            continue
        lease = DB["leases"].get(i["lease_id"])
        if lease is None or lease["lease_status"] not in ("PENDING_SIGNATURE", "ACTIVE", "TERMINATED"):
            continue
        if cd > add_days(parse_date(i["due_date"]), LATE_GRACE_DAYS):
            i["status"] = "LATE"
            touch(i)
            late_count += 1
            affected_leases.add(lease["id"])
    for lid in affected_leases:
        lease = DB["leases"][lid]
        recompute_lease_funding(lease)
        touch(lease)

    activated = 0
    completed = 0
    subs = sorted(DB["sublets"].values(), key=lambda s: s["_seq"])
    for s in subs:
        if s["status"] == "APPROVED" and parse_date(s["start_date"]) <= cd:
            s["status"] = "ACTIVE"
            touch(s)
            activated += 1
    for s in subs:
        if s["status"] == "ACTIVE" and parse_date(s["end_date"]) <= cd:
            s["status"] = "COMPLETED"
            touch(s)
            completed += 1

    ended = 0
    for lease in sorted(DB["leases"].values(), key=lambda l: l["_seq"]):
        if lease["lease_status"] == "ACTIVE" and parse_date(lease["term_end_date"]) <= cd:
            lease["lease_status"] = "ENDED"
            touch(lease)
            release_bed(lease)
            ended += 1

    return respond_object({
        "current_utc": render_logical(new_dt),
        "installments_marked_late_count": late_count,
        "sublets_activated_count": activated,
        "sublets_completed_count": completed,
        "leases_ended_count": ended,
    }, 200)


# ===========================================================================
# UNIVERSITIES
# ===========================================================================
@app.route("/universities", methods=["POST"])
def universities_create():
    authenticate({"PlatformAdmin"})
    body = get_body()
    name = require_str(body, "name")
    code = require_str(body, "code")
    if not re.match(r"^[A-Z0-9]{2,8}$", code):
        err("ERR_VALIDATION", "code must be 2-8 uppercase alphanumeric characters.")
    partner_tier = optional_enum(body, "partner_tier", {"STANDARD", "PREFERRED"}, "STANDARD")
    verification_required = optional_bool(body, "verification_required", True)
    ay_start = require_date(body, "academic_year_start_date")
    ay_end = require_date(body, "academic_year_end_date")
    if ay_end <= ay_start:
        err("ERR_VALIDATION", "academic_year_end_date must be strictly after academic_year_start_date.")
    partner_admin_user_id = require_str(body, "partner_admin_user_id")
    for u in DB["universities"].values():
        if u["code"] == code:
            err("ERR_UNIVERSITY_CODE_TAKEN", "University code already in use.")
    discount = PARTNER_DISCOUNT_BPS_PREFERRED if partner_tier == "PREFERRED" else PARTNER_DISCOUNT_BPS_STANDARD
    ent = make_entity(
        name=name, code=code, partner_tier=partner_tier,
        partner_discount_bps=discount, verification_required=verification_required,
        academic_year_start_date=body["academic_year_start_date"],
        academic_year_end_date=body["academic_year_end_date"],
        partner_admin_user_id=partner_admin_user_id,
        verified_student_count=0,
    )
    DB["universities"][ent["id"]] = ent
    return respond_object(public(ent), 201)


@app.route("/universities/<uid>", methods=["GET"])
def universities_get(uid):
    authenticate(ROLES)
    return respond_object(public(get_university(uid)), 200)


# ===========================================================================
# PROPERTIES
# ===========================================================================
@app.route("/properties", methods=["POST"])
def properties_create():
    caller, _ = authenticate({"PropertyManager"})
    body = get_body()
    university_id = require_present(body, "university_id")
    get_university(university_id)
    name = require_str(body, "name")
    address_line = require_str(body, "address_line")
    distance = require_int(body, "distance_to_campus_m", minimum=0)
    ent = make_entity(
        university_id=university_id, manager_user_id=caller, name=name,
        address_line=address_line, distance_to_campus_m=distance,
        status="DRAFT", unit_count=0, total_bed_count=0, available_bed_count=0,
        escrow_balance_cents=0, maintenance_reserve_cents=0, payout_eligible=False,
    )
    DB["properties"][ent["id"]] = ent
    return respond_object(public(ent), 201)


@app.route("/properties/<pid>", methods=["GET"])
def properties_get(pid):
    authenticate(ROLES)
    return respond_object(public(get_property(pid)), 200)


@app.route("/properties", methods=["GET"])
def properties_list():
    authenticate(ROLES)
    limit, offset = parse_pagination()
    rows = list_rows("properties", ["university_id", "status", "manager_user_id"])
    items, total = paginate(rows, limit, offset)
    return respond_array(items, limit, offset, total)


@app.route("/properties/<pid>/list", methods=["POST"])
def properties_publish(pid):
    caller, _ = authenticate({"PropertyManager"})
    prop = get_property(pid)
    require_manager_owns_property(caller, prop)
    if prop["status"] != "DRAFT":
        err("ERR_PROPERTY_INVALID_STATE", "Only a DRAFT property can be listed.")
    if prop["unit_count"] < 1:
        err("ERR_PROPERTY_HAS_NO_UNITS", "Property has no units.")
    prop["status"] = "LISTED"
    touch(prop)
    recompute_property_rollup(prop)
    return respond_object(public(prop), 200)


@app.route("/properties/<pid>/suspend", methods=["POST"])
def properties_suspend(pid):
    authenticate({"PlatformAdmin"})
    prop = get_property(pid)
    if prop["status"] not in ("LISTED", "FULLY_COMMITTED"):
        err("ERR_PROPERTY_INVALID_STATE", "Only a LISTED or FULLY_COMMITTED property can be suspended.")
    prop["status"] = "SUSPENDED"
    touch(prop)
    return respond_object(public(prop), 200)


@app.route("/properties/<pid>/reinstate", methods=["POST"])
def properties_reinstate(pid):
    authenticate({"PlatformAdmin"})
    prop = get_property(pid)
    if prop["status"] != "SUSPENDED":
        err("ERR_PROPERTY_INVALID_STATE", "Only a SUSPENDED property can be reinstated.")
    prop["status"] = "LISTED" if prop["available_bed_count"] > 0 else "FULLY_COMMITTED"
    touch(prop)
    return respond_object(public(prop), 200)


# ===========================================================================
# UNITS
# ===========================================================================
@app.route("/units", methods=["POST"])
def units_create():
    caller, _ = authenticate({"PropertyManager"})
    body = get_body()
    property_id = require_present(body, "property_id")
    prop = get_property(property_id)
    require_manager_owns_property(caller, prop)
    unit_number = require_str(body, "unit_number")
    floorplan_code = require_str(body, "floorplan_code")
    bedroom_count = require_int(body, "bedroom_count", minimum=1, maximum=8)
    bathroom_count = require_int(body, "bathroom_count", minimum=1)
    bed_labels = require_present(body, "bed_labels")
    if (not isinstance(bed_labels, list) or len(bed_labels) == 0
            or not all(isinstance(x, str) and x != "" for x in bed_labels)
            or len(set(bed_labels)) != len(bed_labels)):
        err("ERR_VALIDATION", "bed_labels must be a non-empty array of distinct strings.")
    base_rent = require_int(body, "base_rent_cents_per_bed_monthly", minimum=1)
    for u in DB["units"].values():
        if u["property_id"] == property_id and u["unit_number"] == unit_number:
            err("ERR_DUPLICATE_UNIT_NUMBER", "unit_number already used in this property.")
    if len(bed_labels) != bedroom_count:
        err("ERR_BED_LABELS_MISMATCH", "len(bed_labels) must equal bedroom_count.")
    ent = make_entity(
        property_id=property_id, unit_number=unit_number, floorplan_code=floorplan_code,
        bedroom_count=bedroom_count, bathroom_count=bathroom_count,
        bed_labels=list(bed_labels), base_rent_cents_per_bed_monthly=base_rent,
        leased_bed_count=0, available_bed_count=len(bed_labels), occupancy_status="AVAILABLE",
    )
    DB["units"][ent["id"]] = ent
    recompute_property_rollup(prop)
    return respond_object(public(ent), 201)


@app.route("/units/<uid>", methods=["GET"])
def units_get(uid):
    authenticate(ROLES)
    return respond_object(public(get_unit(uid)), 200)


@app.route("/units", methods=["GET"])
def units_list():
    authenticate(ROLES)
    limit, offset = parse_pagination()
    rows = list_rows("units", ["property_id", "occupancy_status", "floorplan_code"])
    items, total = paginate(rows, limit, offset)
    return respond_array(items, limit, offset, total)


# ===========================================================================
# STUDENTS
# ===========================================================================
@app.route("/students", methods=["POST"])
def students_create():
    authenticate({"PlatformAdmin"})
    body = get_body()
    university_id = require_present(body, "university_id")
    get_university(university_id)
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    credit_score_band = optional_enum(
        body, "credit_score_band", {"THIN", "LOW", "FAIR", "GOOD", "EXCELLENT"}, "FAIR")
    cleanliness_level = require_int(body, "cleanliness_level", minimum=1, maximum=5)
    noise_tolerance = require_int(body, "noise_tolerance", minimum=1, maximum=5)
    sleep_schedule = require_enum(body, "sleep_schedule", {"EARLY", "LATE"})
    smoker = optional_bool(body, "smoker", False)
    for s in DB["students"].values():
        if s["email"] == email:
            err("ERR_EMAIL_TAKEN", "email already in use.")
    ent = make_entity(
        university_id=university_id, full_name=full_name, email=email,
        credit_score_band=credit_score_band, cleanliness_level=cleanliness_level,
        noise_tolerance=noise_tolerance, sleep_schedule=sleep_schedule, smoker=smoker,
        verification_status="UNVERIFIED", verification_submitted_at=None,
        verification_expires_at=None, verification_decided_at=None,
    )
    DB["students"][ent["id"]] = ent
    return respond_object(public(ent), 201)


@app.route("/students/<sid>", methods=["GET"])
def students_get(sid):
    authenticate(ROLES)
    return respond_object(public(get_student(sid)), 200)


@app.route("/students", methods=["GET"])
def students_list():
    authenticate(ROLES)
    limit, offset = parse_pagination()
    rows = list_rows("students", ["university_id", "verification_status"])
    items, total = paginate(rows, limit, offset)
    return respond_array(items, limit, offset, total)


@app.route("/students/<sid>/verification-requests", methods=["POST"])
def students_verification_request(sid):
    caller, _ = authenticate({"Student"})
    student = get_student(sid)
    require_student_owns(caller, student["id"])
    if student["verification_status"] not in ("UNVERIFIED", "REJECTED"):
        err("ERR_STUDENT_INVALID_STATE", "Verification can only be requested from UNVERIFIED or REJECTED.")
    student["verification_status"] = "PENDING"
    student["verification_submitted_at"] = clock_stamp()
    student["verification_expires_at"] = render_logical(clock_now() + timedelta(days=VERIFICATION_TOKEN_TTL_DAYS))
    touch(student)
    return respond_object(public(student), 200)


@app.route("/students/<sid>/verification-decision", methods=["POST"])
def students_verification_decision(sid):
    caller, _ = authenticate({"UniversityPartner"})
    student = get_student(sid)
    university = DB["universities"].get(student["university_id"])
    if university is None or university["partner_admin_user_id"] != caller:
        err("ERR_NOT_RESOURCE_OWNER", "Caller is not the partner admin for this student's university.")
    body = get_body()
    decision = require_enum(body, "decision", {"APPROVE", "REJECT"})
    if student["verification_status"] != "PENDING":
        err("ERR_STUDENT_INVALID_STATE", "Only a PENDING student can be decided.")
    expires = student["verification_expires_at"]
    if expires is not None and clock_now() > parse_instant(expires):
        err("ERR_VERIFICATION_EXPIRED", "The verification window has expired.")
    if decision == "APPROVE":
        student["verification_status"] = "VERIFIED"
        student["verification_decided_at"] = clock_stamp()
        university["verified_student_count"] += 1
        touch(university)
    else:
        student["verification_status"] = "REJECTED"
        student["verification_decided_at"] = clock_stamp()
    touch(student)
    return respond_object(public(student), 200)


# ===========================================================================
# AMENITIES
# ===========================================================================
@app.route("/amenities", methods=["POST"])
def amenities_create():
    caller, _ = authenticate({"PropertyManager"})
    body = get_body()
    property_id = require_present(body, "property_id")
    prop = get_property(property_id)
    require_manager_owns_property(caller, prop)
    name = require_str(body, "name")
    amenity_type = require_enum(body, "amenity_type", {"PARKING", "STORAGE", "GYM", "STUDY_ROOM", "LAUNDRY"})
    capacity = require_int(body, "capacity", minimum=1)
    monthly_fee_cents = require_int(body, "monthly_fee_cents", minimum=0)
    ent = make_entity(
        property_id=property_id, name=name, amenity_type=amenity_type,
        capacity=capacity, monthly_fee_cents=monthly_fee_cents, active_assignment_count=0,
    )
    DB["amenities"][ent["id"]] = ent
    return respond_object(public(ent), 201)


@app.route("/amenities/<aid>", methods=["GET"])
def amenities_get(aid):
    authenticate(ROLES)
    return respond_object(public(get_amenity(aid)), 200)


@app.route("/amenities", methods=["GET"])
def amenities_list():
    authenticate(ROLES)
    limit, offset = parse_pagination()
    rows = list_rows("amenities", ["property_id", "amenity_type"])
    items, total = paginate(rows, limit, offset)
    return respond_array(items, limit, offset, total)


# ===========================================================================
# ROOMMATE GROUPS & MEMBERSHIPS
# ===========================================================================
def memberships_of_group(gid):
    return [m for m in DB["group_memberships"].values() if m["group_id"] == gid]


def recompute_group_accepted(group):
    group["accepted_member_count"] = sum(
        1 for m in memberships_of_group(group["id"]) if m["status"] in ("ACCEPTED", "PLACED"))


def accepted_member_students(group):
    out = []
    for m in sorted(memberships_of_group(group["id"]), key=lambda x: x["sequence_number"]):
        if m["status"] in ("ACCEPTED", "PLACED"):
            st = DB["students"].get(m["student_id"])
            if st is not None:
                out.append(st)
    return out


@app.route("/roommate-groups", methods=["POST"])
def groups_create():
    caller, _ = authenticate({"Student"})
    body = get_body()
    property_id = require_present(body, "property_id")
    get_property(property_id)
    name = require_str(body, "name")
    required_size = require_int(body, "required_size", minimum=GROUP_MIN_SIZE, maximum=GROUP_MAX_SIZE)
    group = make_entity(
        property_id=property_id, lead_student_id=caller, name=name,
        required_size=required_size, status="FORMING", accepted_member_count=1,
        average_match_score=None, lead_anchored_mean_score=None, placed_unit_id=None,
    )
    DB["roommate_groups"][group["id"]] = group
    member = make_entity(
        group_id=group["id"], student_id=caller, sequence_number=1,
        status="ACCEPTED", match_score=100,
    )
    DB["group_memberships"][member["id"]] = member
    return respond_object(public(group), 201)


@app.route("/roommate-groups/<gid>", methods=["GET"])
def groups_get(gid):
    authenticate(ROLES)
    return respond_object(public(get_group(gid)), 200)


@app.route("/roommate-groups", methods=["GET"])
def groups_list():
    authenticate(ROLES)
    limit, offset = parse_pagination()
    rows = list_rows("roommate_groups", ["property_id", "lead_student_id", "placed_unit_id", "status"])
    items, total = paginate(rows, limit, offset)
    return respond_array(items, limit, offset, total)


@app.route("/roommate-groups/<gid>/invitations", methods=["POST"])
def groups_invite(gid):
    caller, _ = authenticate({"Student"})
    group = get_group(gid)
    body = get_body()
    student_id = require_present(body, "student_id")
    invitee = get_student(student_id)
    if group["lead_student_id"] != caller:
        err("ERR_NOT_RESOURCE_OWNER", "Only the group lead may invite.")
    if group["status"] != "FORMING":
        err("ERR_GROUP_INVALID_STATE", "Can only invite into a FORMING group.")
    for m in memberships_of_group(gid):
        if m["student_id"] == student_id and m["status"] in ("INVITED", "ACCEPTED", "PLACED"):
            err("ERR_DUPLICATE_MEMBERSHIP", "Student already has an active membership on this group.")
    lead = DB["students"].get(group["lead_student_id"])
    score = pair_score(lead, invitee) if lead is not None else 0
    max_seq = max((m["sequence_number"] for m in memberships_of_group(gid)), default=0)
    member = make_entity(
        group_id=gid, student_id=student_id, sequence_number=max_seq + 1,
        status="INVITED", match_score=score,
    )
    DB["group_memberships"][member["id"]] = member
    return respond_object(public(member), 201)


@app.route("/roommate-groups/<gid>/lock", methods=["POST"])
def groups_lock(gid):
    caller, _ = authenticate({"Student"})
    group = get_group(gid)
    if group["lead_student_id"] != caller:
        err("ERR_NOT_RESOURCE_OWNER", "Only the group lead may lock.")
    if group["status"] != "FORMING":
        err("ERR_GROUP_INVALID_STATE", "Only a FORMING group can be locked.")
    if group["accepted_member_count"] != group["required_size"]:
        err("ERR_GROUP_SIZE_MISMATCH", "accepted_member_count must equal required_size.")
    members = accepted_member_students(group)
    lead = DB["students"].get(group["lead_student_id"])
    n = len(members)
    pairs = []
    for a in range(n):
        for b in range(a + 1, n):
            pairs.append(pair_score(members[a], members[b]))
    avg = round_half_up(sum(pairs), len(pairs)) if pairs else 0
    if avg < GROUP_MIN_AVG_MATCH_SCORE:
        err("ERR_GROUP_MATCH_SCORE_TOO_LOW", "Average pairwise match score below the lock threshold.")
    lead_anchored = round_half_up(sum(pair_score(lead, m) for m in members), n)
    group["average_match_score"] = avg
    group["lead_anchored_mean_score"] = lead_anchored
    group["status"] = "LOCKED"
    touch(group)
    return respond_object(public(group), 200)


@app.route("/roommate-groups/<gid>/place", methods=["POST"])
def groups_place(gid):
    caller, _ = authenticate({"PropertyManager"})
    group = get_group(gid)
    body = get_body()
    unit_id = require_present(body, "unit_id")
    unit = get_unit(unit_id)
    group_prop = get_property(group["property_id"])
    require_manager_owns_property(caller, group_prop)
    expected_unit_version = require_int(body, "expected_unit_version")
    ts = require_date(body, "term_start_date")
    te = require_date(body, "term_end_date")
    if te <= ts:
        err("ERR_VALIDATION", "term_end_date must be strictly after term_start_date.")
    installment_count = require_int(body, "installment_count",
                                    minimum=MIN_INSTALLMENT_COUNT, maximum=MAX_INSTALLMENT_COUNT)
    if expected_unit_version != unit["version"]:
        err("ERR_STALE_VERSION", "expected_unit_version does not match the unit's current version.")
    if group["status"] != "LOCKED":
        err("ERR_GROUP_INVALID_STATE", "Only a LOCKED group can be placed.")
    if group_prop["status"] not in ("LISTED", "FULLY_COMMITTED"):
        err("ERR_PROPERTY_NOT_ACTIVE", "Property is not active.")
    members = [m for m in sorted(memberships_of_group(gid), key=lambda x: x["sequence_number"])
               if m["status"] == "ACCEPTED"]
    for m in members:
        st = DB["students"].get(m["student_id"])
        uni = DB["universities"].get(st["university_id"]) if st else None
        if uni is not None and uni["verification_required"] and st["verification_status"] != "VERIFIED":
            err("ERR_STUDENT_NOT_VERIFIED", "A placed member is not verified.")
    if unit["property_id"] != group["property_id"]:
        err("ERR_UNIT_PROPERTY_MISMATCH", "Unit belongs to a different property than the group.")
    term_days = date_diff_days(te, ts)
    if term_days < MIN_LEASE_TERM_DAYS or term_days > MAX_LEASE_TERM_DAYS:
        err("ERR_TERM_LENGTH_INVALID", "term_days out of range.")
    if ts < clock_date():
        err("ERR_TERM_START_IN_PAST", "term_start_date is in the past.")
    occupied = {l["bed_label"] for l in leases_of_unit(unit_id) if l["lease_status"] in HOLDING}
    vacant = sorted([b for b in unit["bed_labels"] if b not in occupied])
    for bed in vacant[:group["required_size"]]:
        if bed_slot_conflict(unit_id, bed, ts, te):
            err("ERR_BED_TURNOVER_CONFLICT", "Bed-slot turnover conflict.")
    if unit["available_bed_count"] < group["required_size"]:
        err("ERR_UNIT_CAPACITY_INSUFFICIENT", "Unit does not have enough available beds.")

    # cascade
    group["status"] = "PLACED"
    group["placed_unit_id"] = unit_id
    touch(group)
    for member, bed in zip(members, vacant):
        student = DB["students"][member["student_id"]]
        lease = build_lease(student, unit, bed, ts, te, installment_count, roommate_group_id=gid)
        DB["leases"][lease["id"]] = lease
        lease["lease_status"] = "PENDING_GUARANTOR" if lease["guarantor_required"] else "PENDING_SIGNATURE"
        touch(lease)
        member["status"] = "PLACED"
        touch(member)
    recompute_group_accepted(group)
    recompute_unit_rollup(unit)
    recompute_property_rollup(group_prop)
    return respond_object(public(group), 200)


@app.route("/group-memberships/<mid>", methods=["GET"])
def memberships_get(mid):
    authenticate(ROLES)
    return respond_object(public(get_membership(mid)), 200)


@app.route("/group-memberships", methods=["GET"])
def memberships_list():
    authenticate(ROLES)
    limit, offset = parse_pagination()
    group_filter = request.args.get("group_id")
    if group_filter:
        sort_key = lambda r: r["sequence_number"]
    else:
        sort_key = lambda r: r["_seq"]
    rows = list_rows("group_memberships", ["group_id", "student_id", "status"], sort_key=sort_key)
    items, total = paginate(rows, limit, offset)
    return respond_array(items, limit, offset, total)


@app.route("/group-memberships/<mid>/respond", methods=["POST"])
def memberships_respond(mid):
    caller, _ = authenticate({"Student"})
    member = get_membership(mid)
    if member["student_id"] != caller:
        err("ERR_NOT_RESOURCE_OWNER", "Caller does not own this membership.")
    body = get_body()
    decision = require_enum(body, "decision", {"ACCEPT", "DECLINE"})
    group = DB["roommate_groups"].get(member["group_id"])
    if member["status"] != "INVITED":
        err("ERR_MEMBERSHIP_INVALID_STATE", "Membership is no longer INVITED.")
    if group is None or group["status"] != "FORMING":
        err("ERR_GROUP_INVALID_STATE", "Group is not FORMING.")
    member["status"] = "ACCEPTED" if decision == "ACCEPT" else "DECLINED"
    touch(member)
    recompute_group_accepted(group)
    touch(group)
    return respond_object(public(member), 200)


# ===========================================================================
# LEASES & INSTALLMENTS
# ===========================================================================
def build_lease(student, unit, bed_label, ts_date, te_date, installment_count,
                roommate_group_id=None, replaces_lease_id=None):
    term_days = date_diff_days(te_date, ts_date)
    monthly = unit["base_rent_cents_per_bed_monthly"]
    quoted = monthly * ceil_div(term_days, QUOTE_MONTH_DAYS)
    guar = lease_guarantor_required(student, monthly)
    return make_entity(
        student_id=student["id"], unit_id=unit["id"], property_id=unit["property_id"],
        roommate_group_id=roommate_group_id, replaces_lease_id=replaces_lease_id,
        bed_label=bed_label,
        term_start_date=ts_date.isoformat(), term_end_date=te_date.isoformat(),
        term_days=term_days, term_type=None, monthly_rent_cents=monthly,
        daily_rate_cents=None, quoted_total_cents=quoted, total_contract_cents=None,
        partner_discount_bps=None, partner_discount_cents=None,
        installment_count=installment_count, guarantor_required=guar,
        lease_status="DRAFT", funding_status="UNFUNDED",
        amenity_fee_total_cents=0, billed_total_cents=0, paid_cents=0,
        signed_at=None, terminated_at=None,
    )


@app.route("/leases", methods=["POST"])
def leases_create():
    caller, _ = authenticate({"Student"})
    body = get_body()
    student_id = require_present(body, "student_id")
    student = get_student(student_id)
    unit_id = require_present(body, "unit_id")
    unit = get_unit(unit_id)
    require_student_owns(caller, student_id)
    bed_label = require_str(body, "bed_label")
    ts = require_date(body, "term_start_date")
    te = require_date(body, "term_end_date")
    if te <= ts:
        err("ERR_VALIDATION", "term_end_date must be strictly after term_start_date.")
    installment_count = require_int(body, "installment_count",
                                    minimum=MIN_INSTALLMENT_COUNT, maximum=MAX_INSTALLMENT_COUNT)
    if bed_label not in unit["bed_labels"]:
        err("ERR_BED_LABEL_UNKNOWN", "bed_label is not a member of the unit's bed_labels.")
    term_days = date_diff_days(te, ts)
    if term_days < MIN_LEASE_TERM_DAYS or term_days > MAX_LEASE_TERM_DAYS:
        err("ERR_TERM_LENGTH_INVALID", "term_days out of range.")
    if ts < clock_date():
        err("ERR_TERM_START_IN_PAST", "term_start_date is in the past.")
    if bed_slot_conflict(unit_id, bed_label, ts, te):
        err("ERR_BED_TURNOVER_CONFLICT", "Bed-slot turnover conflict.")
    lease = build_lease(student, unit, bed_label, ts, te, installment_count)
    DB["leases"][lease["id"]] = lease
    return respond_object(public(lease), 201)


@app.route("/leases/<lid>", methods=["GET"])
def leases_get(lid):
    authenticate(ROLES)
    return respond_object(public(get_lease(lid)), 200)


@app.route("/leases", methods=["GET"])
def leases_list():
    authenticate(ROLES)
    limit, offset = parse_pagination()
    rows = list_rows("leases", ["student_id", "unit_id", "property_id", "roommate_group_id",
                                 "replaces_lease_id", "lease_status", "funding_status"])
    items, total = paginate(rows, limit, offset)
    return respond_array(items, limit, offset, total)


@app.route("/leases/<lid>/submit", methods=["POST"])
def leases_submit(lid):
    caller, _ = authenticate({"Student"})
    lease = get_lease(lid)
    require_student_owns(caller, lease["student_id"])
    if lease["lease_status"] != "DRAFT":
        err("ERR_LEASE_INVALID_STATE", "Only a DRAFT lease can be submitted.")
    prop = property_of_lease(lease)
    if prop is None or prop["status"] not in ("LISTED", "FULLY_COMMITTED"):
        err("ERR_PROPERTY_NOT_ACTIVE", "Property is not active.")
    student = DB["students"][lease["student_id"]]
    uni = DB["universities"].get(student["university_id"])
    if uni is not None and uni["verification_required"] and student["verification_status"] != "VERIFIED":
        err("ERR_STUDENT_NOT_VERIFIED", "Student is not verified.")
    if bed_slot_conflict(lease["unit_id"], lease["bed_label"], lease["term_start_date"], lease["term_end_date"]):
        err("ERR_BED_TURNOVER_CONFLICT", "Bed-slot turnover conflict.")
    lease["lease_status"] = "PENDING_GUARANTOR" if lease["guarantor_required"] else "PENDING_SIGNATURE"
    touch(lease)
    reserve_bed(lease)
    return respond_object(public(lease), 200)


@app.route("/leases/<lid>/sign", methods=["POST"])
def leases_sign(lid):
    caller, _ = authenticate({"Student"})
    lease = get_lease(lid)
    require_student_owns(caller, lease["student_id"])
    if lease["lease_status"] != "PENDING_SIGNATURE":
        err("ERR_LEASE_INVALID_STATE", "Only a PENDING_SIGNATURE lease can be signed.")
    prop = property_of_lease(lease)
    if prop is None or prop["status"] not in ("LISTED", "FULLY_COMMITTED"):
        err("ERR_PROPERTY_NOT_ACTIVE", "Property is not active.")
    student = DB["students"][lease["student_id"]]
    uni = DB["universities"].get(student["university_id"])
    ts = parse_date(lease["term_start_date"])
    te = parse_date(lease["term_end_date"])
    monthly = lease["monthly_rent_cents"]
    term_days = lease["term_days"]
    academic_year = False
    if uni is not None:
        ay_start = parse_date(uni["academic_year_start_date"])
        ay_end = parse_date(uni["academic_year_end_date"])
        academic_year = (ts <= ay_start and te >= ay_end)
    term_type = "ACADEMIC_YEAR" if academic_year else "PARTIAL_TERM"
    daily_rate = round_half_up(monthly * 12, DAYS_PER_YEAR)
    gross = daily_rate * term_days
    discount_bps = (uni["partner_discount_bps"] if (academic_year and uni is not None) else 0)
    discount_cents = round_half_up(gross * discount_bps, 10000)
    total_contract = gross - discount_cents
    lease["term_type"] = term_type
    lease["daily_rate_cents"] = daily_rate
    lease["partner_discount_bps"] = discount_bps
    lease["partner_discount_cents"] = discount_cents
    lease["total_contract_cents"] = total_contract
    lease["lease_status"] = "ACTIVE"
    lease["signed_at"] = clock_stamp()
    # mint RENT installments
    n = lease["installment_count"]
    base = floor_div(total_contract, n)
    for k in range(1, n + 1):
        amount = base if k < n else (total_contract - base * (n - 1))
        due = add_days(ts, (k - 1) * INSTALLMENT_INTERVAL_DAYS)
        inst = make_entity(
            lease_id=lease["id"], kind="RENT", sequence_number=k,
            due_date=due.isoformat(), amount_cents=amount, status="SCHEDULED",
            late_fee_cents=0, paid_cents=0, paid_at=None,
        )
        DB["installments"][inst["id"]] = inst
    recompute_lease_funding(lease)
    touch(lease)
    return respond_object(public(lease), 200)


@app.route("/leases/<lid>/cancel", methods=["POST"])
def leases_cancel(lid):
    caller, _ = authenticate({"Student"})
    lease = get_lease(lid)
    require_student_owns(caller, lease["student_id"])
    if lease["lease_status"] not in ("DRAFT", "PENDING_GUARANTOR", "PENDING_SIGNATURE"):
        err("ERR_LEASE_INVALID_STATE", "Only an unsigned lease can be cancelled.")
    was_holding = lease["lease_status"] in HOLDING
    lease["lease_status"] = "CANCELLED"
    lease["terminated_at"] = clock_stamp()
    touch(lease)
    for ga in DB["guarantor_applications"].values():
        if ga["lease_id"] == lid and ga["status"] in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED"):
            ga["status"] = "DECLINED"
            touch(ga)
    if was_holding:
        release_bed(lease)
    return respond_object(public(lease), 200)


@app.route("/leases/<lid>/terminate", methods=["POST"])
def leases_terminate(lid):
    caller, _ = authenticate({"PropertyManager"})
    lease = get_lease(lid)
    prop = property_of_lease(lease)
    if prop is None or prop["manager_user_id"] != caller:
        err("ERR_NOT_RESOURCE_OWNER", "Caller is not the property manager.")
    if lease["lease_status"] != "ACTIVE":
        err("ERR_LEASE_INVALID_STATE", "Only an ACTIVE lease can be terminated.")
    cd = clock_date()
    lease["lease_status"] = "TERMINATED"
    lease["terminated_at"] = clock_stamp()
    touch(lease)
    for inst in installments_of_lease(lid):
        if inst["status"] in ("SCHEDULED", "LATE") and parse_date(inst["due_date"]) > cd:
            inst["status"] = "VOID"
            touch(inst)
    recompute_lease_funding(lease)
    release_bed(lease)
    for asg in DB["amenity_assignments"].values():
        if asg["lease_id"] == lid and asg["status"] == "ACTIVE":
            asg["status"] = "RELEASED"
            asg["released_at"] = clock_stamp()
            touch(asg)
            amenity = DB["amenities"].get(asg["amenity_id"])
            if amenity is not None:
                amenity["active_assignment_count"] = max(0, amenity["active_assignment_count"] - 1)
                touch(amenity)
    for sub in DB["sublets"].values():
        if sub["lease_id"] == lid and sub["status"] in ("REQUESTED", "APPROVED", "ACTIVE"):
            sub["status"] = "COMPLETED"
            touch(sub)
    return respond_object(public(lease), 200)


@app.route("/leases/<lid>/renew", methods=["POST"])
def leases_renew(lid):
    caller, _ = authenticate({"Student"})
    lease = get_lease(lid)
    require_student_owns(caller, lease["student_id"])
    body = get_body()
    ts = require_date(body, "term_start_date")
    te = require_date(body, "term_end_date")
    if te <= ts:
        err("ERR_VALIDATION", "term_end_date must be strictly after term_start_date.")
    installment_count = require_int(body, "installment_count",
                                    minimum=MIN_INSTALLMENT_COUNT, maximum=MAX_INSTALLMENT_COUNT)
    if lease["lease_status"] != "ACTIVE":
        err("ERR_LEASE_NOT_ACTIVE", "Only an ACTIVE lease can be renewed.")
    term_days = date_diff_days(te, ts)
    if term_days < MIN_LEASE_TERM_DAYS or term_days > MAX_LEASE_TERM_DAYS:
        err("ERR_TERM_LENGTH_INVALID", "term_days out of range.")
    if ts < clock_date():
        err("ERR_TERM_START_IN_PAST", "term_start_date is in the past.")
    if bed_slot_conflict(lease["unit_id"], lease["bed_label"], ts, te):
        err("ERR_BED_TURNOVER_CONFLICT", "Bed-slot turnover conflict.")
    student = DB["students"][lease["student_id"]]
    unit = DB["units"][lease["unit_id"]]
    successor = build_lease(student, unit, lease["bed_label"], ts, te, installment_count,
                            replaces_lease_id=lid)
    DB["leases"][successor["id"]] = successor
    return respond_object(public(successor), 201)


@app.route("/leases/<lid>/installments", methods=["GET"])
def leases_installments(lid):
    authenticate(ROLES)
    get_lease(lid)
    limit, offset = parse_pagination()
    rows = [i for i in DB["installments"].values() if i["lease_id"] == lid]
    kind = request.args.get("kind")
    status = request.args.get("status")
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["sequence_number"])
    items, total = paginate(rows, limit, offset)
    return respond_array(items, limit, offset, total)


@app.route("/installments/<iid>/pay", methods=["POST"])
def installments_pay(iid):
    caller, _ = authenticate({"Student"})
    inst = get_installment(iid)
    lease = DB["leases"].get(inst["lease_id"])
    if lease is None or lease["student_id"] != caller:
        err("ERR_NOT_RESOURCE_OWNER", "Caller does not own this installment's lease.")
    body = get_body()
    amount = require_int(body, "amount_cents")
    if inst["status"] not in ("SCHEDULED", "LATE") or lease["lease_status"] not in ("ACTIVE", "TERMINATED"):
        err("ERR_INSTALLMENT_NOT_PAYABLE", "Installment is not payable.")
    if amount != inst["amount_cents"]:
        err("ERR_PAYMENT_AMOUNT_MISMATCH", "amount_cents must equal the installment amount exactly.")
    if inst["status"] == "LATE":
        fee = min(round_half_up(inst["amount_cents"] * LATE_FEE_BPS, 10000), LATE_FEE_CAP_CENTS)
    else:
        fee = 0
    inst["late_fee_cents"] = fee
    inst["status"] = "PAID"
    inst["paid_cents"] = inst["amount_cents"] + fee
    inst["paid_at"] = clock_stamp()
    touch(inst)
    recompute_lease_funding(lease)
    touch(lease)
    prop = property_of_lease(lease)
    if prop is not None:
        recompute_escrow(prop)
    return respond_object(public(inst), 200)


# ===========================================================================
# GUARANTOR APPLICATIONS
# ===========================================================================
@app.route("/guarantor-applications", methods=["POST"])
def guarantor_create():
    caller, _ = authenticate({"Student"})
    body = get_body()
    lease_id = require_present(body, "lease_id")
    lease = get_lease(lease_id)
    require_student_owns(caller, lease["student_id"])
    guarantor_full_name = require_str(body, "guarantor_full_name")
    income = require_int(body, "guarantor_annual_income_cents", minimum=0)
    relationship = require_enum(body, "relationship",
                                {"PARENT", "GUARDIAN", "RELATIVE", "EMPLOYER", "OTHER"})
    if not lease["guarantor_required"]:
        err("ERR_GUARANTOR_NOT_REQUIRED", "Lease does not require a guarantor.")
    for ga in DB["guarantor_applications"].values():
        if ga["lease_id"] == lease_id and ga["status"] in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED"):
            err("ERR_GUARANTOR_NOT_REQUIRED", "Lease already has an active guarantor application.")
    bps = guarantor_income_multiple_bps(income, lease["monthly_rent_cents"])
    ent = make_entity(
        lease_id=lease_id, guarantor_full_name=guarantor_full_name,
        guarantor_annual_income_cents=income, relationship=relationship,
        income_multiple_bps=bps, status="SUBMITTED", round_count=1,
        reviewer_user_id=None, decision_note=None, decided_at=None,
    )
    DB["guarantor_applications"][ent["id"]] = ent
    return respond_object(public(ent), 201)


@app.route("/guarantor-applications/<gid>", methods=["GET"])
def guarantor_get(gid):
    authenticate(ROLES)
    return respond_object(public(get_guarantor(gid)), 200)


@app.route("/guarantor-applications", methods=["GET"])
def guarantor_list():
    authenticate(ROLES)
    limit, offset = parse_pagination()
    rows = list_rows("guarantor_applications", ["lease_id", "status"])
    items, total = paginate(rows, limit, offset)
    return respond_array(items, limit, offset, total)


@app.route("/guarantor-applications/<gid>/review", methods=["POST"])
def guarantor_review(gid):
    caller, _ = authenticate({"PropertyManager"})
    ga = get_guarantor(gid)
    lease = DB["leases"].get(ga["lease_id"])
    prop = property_of_lease(lease) if lease else None
    if prop is None or prop["manager_user_id"] != caller:
        err("ERR_NOT_RESOURCE_OWNER", "Caller is not the property manager.")
    body = get_body()
    decision = require_enum(body, "decision", {"START_REVIEW", "REQUEST_INFO", "APPROVE", "DECLINE"})
    note = body.get("note")
    if decision == "START_REVIEW":
        if ga["status"] != "SUBMITTED":
            err("ERR_GUARANTOR_INVALID_STATE", "START_REVIEW requires a SUBMITTED application.")
        ga["status"] = "UNDER_REVIEW"
        ga["reviewer_user_id"] = caller
        touch(ga)
    elif decision == "REQUEST_INFO":
        if ga["status"] != "UNDER_REVIEW":
            err("ERR_GUARANTOR_INVALID_STATE", "REQUEST_INFO requires an UNDER_REVIEW application.")
        ga["status"] = "INFO_REQUESTED"
        ga["reviewer_user_id"] = caller
        ga["decision_note"] = note
        touch(ga)
    elif decision == "APPROVE":
        if ga["status"] != "UNDER_REVIEW":
            err("ERR_GUARANTOR_INVALID_STATE", "APPROVE requires an UNDER_REVIEW application.")
        if ga["income_multiple_bps"] < GUARANTOR_MIN_INCOME_MULTIPLE_BPS:
            err("ERR_GUARANTOR_INCOME_INSUFFICIENT", "Guarantor income multiple is insufficient.")
        ga["status"] = "APPROVED"
        ga["decided_at"] = clock_stamp()
        ga["reviewer_user_id"] = caller
        touch(ga)
        if lease is not None and lease["lease_status"] == "PENDING_GUARANTOR":
            lease["lease_status"] = "PENDING_SIGNATURE"
            touch(lease)
    else:  # DECLINE
        if ga["status"] != "UNDER_REVIEW":
            err("ERR_GUARANTOR_INVALID_STATE", "DECLINE requires an UNDER_REVIEW application.")
        ga["status"] = "DECLINED"
        ga["decided_at"] = clock_stamp()
        ga["reviewer_user_id"] = caller
        touch(ga)
        if lease is not None and lease["lease_status"] == "PENDING_GUARANTOR":
            lease["lease_status"] = "CANCELLED"
            lease["terminated_at"] = clock_stamp()
            touch(lease)
            release_bed(lease)
    return respond_object(public(ga), 200)


@app.route("/guarantor-applications/<gid>/resubmit", methods=["POST"])
def guarantor_resubmit(gid):
    caller, _ = authenticate({"Student"})
    ga = get_guarantor(gid)
    lease = DB["leases"].get(ga["lease_id"])
    if lease is None or lease["student_id"] != caller:
        err("ERR_NOT_RESOURCE_OWNER", "Caller does not own this application's lease.")
    body = get_body()
    guarantor_full_name = require_str(body, "guarantor_full_name")
    income = require_int(body, "guarantor_annual_income_cents", minimum=0)
    if ga["status"] != "INFO_REQUESTED":
        err("ERR_GUARANTOR_INVALID_STATE", "Only an INFO_REQUESTED application can be resubmitted.")
    if ga["round_count"] >= GUARANTOR_MAX_REVIEW_ROUNDS:
        err("ERR_GUARANTOR_MAX_ROUNDS_EXCEEDED", "Maximum review rounds exceeded.")
    ga["guarantor_full_name"] = guarantor_full_name
    ga["guarantor_annual_income_cents"] = income
    ga["income_multiple_bps"] = guarantor_income_multiple_bps(income, lease["monthly_rent_cents"])
    ga["round_count"] += 1
    ga["status"] = "SUBMITTED"
    touch(ga)
    return respond_object(public(ga), 200)


# ===========================================================================
# SUBLETS
# ===========================================================================
def next_installment_seq(lease_id):
    seqs = [i["sequence_number"] for i in installments_of_lease(lease_id)]
    return (max(seqs) + 1) if seqs else 1


@app.route("/sublets", methods=["POST"])
def sublets_create():
    caller, _ = authenticate({"Student"})
    body = get_body()
    lease_id = require_present(body, "lease_id")
    lease = get_lease(lease_id)
    subtenant_student_id = require_present(body, "subtenant_student_id")
    subtenant = get_student(subtenant_student_id)
    require_student_owns(caller, lease["student_id"])
    start = require_date(body, "start_date")
    end = require_date(body, "end_date")
    if end <= start:
        err("ERR_VALIDATION", "end_date must be strictly after start_date.")
    sublet_rent_cents = require_int(body, "sublet_rent_cents", minimum=1)
    prop = property_of_lease(lease)
    if prop is None or prop["status"] not in ("LISTED", "FULLY_COMMITTED"):
        err("ERR_PROPERTY_NOT_ACTIVE", "Property is not active.")
    if lease["lease_status"] != "ACTIVE":
        err("ERR_LEASE_NOT_ACTIVE", "Host lease is not ACTIVE.")
    uni = DB["universities"].get(subtenant["university_id"])
    if uni is not None and uni["verification_required"] and subtenant["verification_status"] != "VERIFIED":
        err("ERR_STUDENT_NOT_VERIFIED", "Subtenant is not verified.")
    if subtenant_student_id == lease["student_id"]:
        err("ERR_SUBTENANT_IS_LEASEHOLDER", "Subtenant must differ from the leaseholder.")
    lease_start = parse_date(lease["term_start_date"])
    lease_end = parse_date(lease["term_end_date"])
    if start < lease_start or end > lease_end:
        err("ERR_WINDOW_OUTSIDE_LEASE_TERM", "Sublet window is outside the lease term.")
    window_days = date_diff_days(end, start)
    if window_days < SUBLET_MIN_TERM_DAYS:
        err("ERR_WINDOW_TOO_SHORT", "Sublet window is too short.")
    for s in DB["sublets"].values():
        if s["lease_id"] != lease_id or s["status"] not in ("REQUESTED", "APPROVED", "ACTIVE"):
            continue
        es = parse_date(s["start_date"])
        ee = parse_date(s["end_date"])
        if start < ee and es < end:
            err("ERR_SUBLET_OVERLAP", "Sublet window overlaps an existing sublet.")
    max_rent = round_half_up(lease["monthly_rent_cents"] * SUBLET_MAX_MARKUP_BPS, 10000)
    if sublet_rent_cents > max_rent:
        err("ERR_SUBLET_RENT_ABOVE_CAP", "Sublet rent exceeds the cap.")
    sublet_total = sublet_rent_cents * ceil_div(window_days, QUOTE_MONTH_DAYS)
    ent = make_entity(
        lease_id=lease_id, subtenant_student_id=subtenant_student_id,
        start_date=start.isoformat(), end_date=end.isoformat(), window_days=window_days,
        sublet_rent_cents=sublet_rent_cents, sublet_total_cents=sublet_total,
        platform_fee_cents=None, installment_id=None, status="REQUESTED",
        decided_by_user_id=None, decided_at=None,
    )
    DB["sublets"][ent["id"]] = ent
    return respond_object(public(ent), 201)


@app.route("/sublets/<sid>", methods=["GET"])
def sublets_get(sid):
    authenticate(ROLES)
    return respond_object(public(get_sublet(sid)), 200)


@app.route("/sublets", methods=["GET"])
def sublets_list():
    authenticate(ROLES)
    limit, offset = parse_pagination()
    rows = list_rows("sublets", ["lease_id", "subtenant_student_id", "installment_id", "status"])
    items, total = paginate(rows, limit, offset)
    return respond_array(items, limit, offset, total)


@app.route("/sublets/<sid>/decision", methods=["POST"])
def sublets_decision(sid):
    caller, _ = authenticate({"PropertyManager"})
    sublet = get_sublet(sid)
    lease = DB["leases"].get(sublet["lease_id"])
    prop = property_of_lease(lease) if lease else None
    if prop is None or prop["manager_user_id"] != caller:
        err("ERR_NOT_RESOURCE_OWNER", "Caller is not the property manager.")
    body = get_body()
    decision = require_enum(body, "decision", {"APPROVE", "DECLINE"})
    if sublet["status"] != "REQUESTED":
        err("ERR_SUBLET_INVALID_STATE", "Only a REQUESTED sublet can be decided.")
    if decision == "APPROVE":
        if prop["status"] not in ("LISTED", "FULLY_COMMITTED"):
            err("ERR_PROPERTY_NOT_ACTIVE", "Property is not active.")
        fee = max(SUBLET_MIN_FEE_CENTS, round_half_up(sublet["sublet_total_cents"] * SUBLET_FEE_BPS, 10000))
        sublet["platform_fee_cents"] = fee
        sublet["status"] = "APPROVED"
        sublet["decided_by_user_id"] = caller
        sublet["decided_at"] = clock_stamp()
        inst = make_entity(
            lease_id=lease["id"], kind="SUBLET_FEE", sequence_number=next_installment_seq(lease["id"]),
            due_date=sublet["start_date"], amount_cents=fee, status="SCHEDULED",
            late_fee_cents=0, paid_cents=0, paid_at=None,
        )
        DB["installments"][inst["id"]] = inst
        sublet["installment_id"] = inst["id"]
        touch(sublet)
        recompute_lease_funding(lease)
        touch(lease)
    else:
        sublet["status"] = "DECLINED"
        sublet["decided_by_user_id"] = caller
        sublet["decided_at"] = clock_stamp()
        touch(sublet)
    return respond_object(public(sublet), 200)


# ===========================================================================
# AMENITY ASSIGNMENTS
# ===========================================================================
@app.route("/amenity-assignments", methods=["POST"])
def assignments_create():
    caller, _ = authenticate({"Student"})
    body = get_body()
    amenity_id = require_present(body, "amenity_id")
    amenity = get_amenity(amenity_id)
    lease_id = require_present(body, "lease_id")
    lease = get_lease(lease_id)
    require_student_owns(caller, lease["student_id"])
    start = require_date(body, "start_date")
    end = require_date(body, "end_date")
    if end < start:
        err("ERR_VALIDATION", "end_date must not be before start_date.")
    if lease["lease_status"] != "ACTIVE":
        err("ERR_LEASE_NOT_ACTIVE", "Host lease is not ACTIVE.")
    if amenity["property_id"] != lease["property_id"]:
        err("ERR_AMENITY_PROPERTY_MISMATCH", "Amenity belongs to a different property than the lease.")
    lease_start = parse_date(lease["term_start_date"])
    lease_end = parse_date(lease["term_end_date"])
    if start < lease_start or end > lease_end:
        err("ERR_WINDOW_OUTSIDE_LEASE_TERM", "Amenity window is outside the lease term.")
    window_days = date_diff_days(end, start) + 1
    if window_days < AMENITY_MIN_TERM_DAYS:
        err("ERR_WINDOW_TOO_SHORT", "Amenity window is too short.")
    # aggregate closed-interval capacity
    active = [a for a in DB["amenity_assignments"].values()
              if a["amenity_id"] == amenity_id and a["status"] == "ACTIVE"]
    intervals = [(parse_date(a["start_date"]), parse_date(a["end_date"])) for a in active]
    d = start
    while d <= end:
        cnt = 1 + sum(1 for (s0, e0) in intervals if s0 <= d <= e0)
        if cnt > amenity["capacity"]:
            err("ERR_AMENITY_CAPACITY_EXCEEDED", "Amenity capacity exceeded on some day.")
        d = add_days(d, 1)
    billed_months = ceil_div(window_days, QUOTE_MONTH_DAYS)
    total_fee = amenity["monthly_fee_cents"] * billed_months
    inst = make_entity(
        lease_id=lease_id, kind="AMENITY", sequence_number=next_installment_seq(lease_id),
        due_date=start.isoformat(), amount_cents=total_fee, status="SCHEDULED",
        late_fee_cents=0, paid_cents=0, paid_at=None,
    )
    DB["installments"][inst["id"]] = inst
    ent = make_entity(
        amenity_id=amenity_id, lease_id=lease_id, start_date=start.isoformat(),
        end_date=end.isoformat(), window_days=window_days, billed_months=billed_months,
        total_fee_cents=total_fee, installment_id=inst["id"], status="ACTIVE", released_at=None,
    )
    DB["amenity_assignments"][ent["id"]] = ent
    amenity["active_assignment_count"] += 1
    touch(amenity)
    recompute_lease_funding(lease)
    touch(lease)
    return respond_object(public(ent), 201)


@app.route("/amenity-assignments/<aid>", methods=["GET"])
def assignments_get(aid):
    authenticate(ROLES)
    return respond_object(public(get_assignment(aid)), 200)


@app.route("/amenity-assignments", methods=["GET"])
def assignments_list():
    authenticate(ROLES)
    limit, offset = parse_pagination()
    rows = list_rows("amenity_assignments", ["amenity_id", "lease_id", "installment_id", "status"])
    items, total = paginate(rows, limit, offset)
    return respond_array(items, limit, offset, total)


@app.route("/amenity-assignments/<aid>/release", methods=["POST"])
def assignments_release(aid):
    caller, _ = authenticate({"Student"})
    asg = get_assignment(aid)
    lease = DB["leases"].get(asg["lease_id"])
    if lease is None or lease["student_id"] != caller:
        err("ERR_NOT_RESOURCE_OWNER", "Caller does not own this assignment's lease.")
    if asg["status"] != "ACTIVE":
        err("ERR_ASSIGNMENT_INVALID_STATE", "Only an ACTIVE assignment can be released.")
    asg["status"] = "RELEASED"
    asg["released_at"] = clock_stamp()
    touch(asg)
    inst = DB["installments"].get(asg["installment_id"])
    if inst is not None and inst["status"] in ("SCHEDULED", "LATE"):
        inst["status"] = "VOID"
        touch(inst)
    amenity = DB["amenities"].get(asg["amenity_id"])
    if amenity is not None:
        amenity["active_assignment_count"] = max(0, amenity["active_assignment_count"] - 1)
        touch(amenity)
    recompute_lease_funding(lease)
    touch(lease)
    return respond_object(public(asg), 200)


# ===========================================================================
# PAYOUTS
# ===========================================================================
def compute_payout_money(prop, ps, pe):
    prop_lease_ids = {l["id"] for l in DB["leases"].values() if l["property_id"] == prop["id"]}
    gross = 0
    for i in DB["installments"].values():
        if i["status"] != "PAID" or i["lease_id"] not in prop_lease_ids or not i["paid_at"]:
            continue
        pd = parse_instant(i["paid_at"]).date()
        if ps <= pd <= pe:
            gross += i["amount_cents"] + i["late_fee_cents"]
    if gross < PAYOUT_TIER1_MAX_CENTS:
        bps = PAYOUT_TIER1_BPS
    elif gross < PAYOUT_TIER2_MAX_CENTS:
        bps = PAYOUT_TIER2_BPS
    else:
        bps = PAYOUT_TIER3_BPS
    fee = round_half_up(gross * bps, 10000)
    holdback = round_half_up(gross * MAINTENANCE_HOLDBACK_BPS, 10000)
    subtotal = gross - fee - holdback
    rebate = round_half_up(fee * PAYOUT_REBATE_PCT_BPS, 10000) if subtotal >= PAYOUT_REBATE_MIN_SUBTOTAL_CENTS else 0
    net = subtotal + rebate
    return gross, bps, fee, holdback, subtotal, rebate, net


@app.route("/payouts", methods=["POST"])
def payouts_create():
    caller, _ = authenticate({"PlatformAdmin"})
    body = get_body()
    property_id = require_present(body, "property_id")
    prop = get_property(property_id)
    ps = require_date(body, "period_start_date")
    pe = require_date(body, "period_end_date")
    if pe < ps:
        err("ERR_VALIDATION", "period_end_date must be at or after period_start_date.")
    expected_property_version = require_int(body, "expected_property_version")
    if expected_property_version != prop["version"]:
        err("ERR_STALE_VERSION", "expected_property_version does not match the property's current version.")
    for p in DB["payouts"].values():
        if p["property_id"] != property_id or p["status"] not in ("SUBMITTED", "APPROVED", "PAID"):
            continue
        eps = parse_date(p["period_start_date"])
        epe = parse_date(p["period_end_date"])
        if ps <= epe and eps <= pe:
            err("ERR_PAYOUT_PERIOD_OVERLAP", "Settlement window overlaps an existing payout.")
    gross, bps, fee, holdback, subtotal, rebate, net = compute_payout_money(prop, ps, pe)
    if gross <= 0:
        err("ERR_PAYOUT_EMPTY_PERIOD", "No collections in the requested window.")
    ent = make_entity(
        property_id=property_id, period_start_date=ps.isoformat(), period_end_date=pe.isoformat(),
        gross_collected_cents=gross, platform_fee_bps=bps, platform_fee_cents=fee,
        holdback_cents=holdback, subtotal_cents=subtotal, rebate_cents=rebate, net_amount_cents=net,
        status="SUBMITTED", submitted_by_user_id=caller, approved_by_user_id=None,
        paid_at=None, reversed_at=None,
    )
    DB["payouts"][ent["id"]] = ent
    touch(prop)
    return respond_object(public(ent), 201)


@app.route("/payouts/<pid>", methods=["GET"])
def payouts_get(pid):
    authenticate({"PlatformAdmin", "PropertyManager"})
    return respond_object(public(get_payout(pid)), 200)


@app.route("/payouts", methods=["GET"])
def payouts_list():
    authenticate({"PlatformAdmin", "PropertyManager"})
    limit, offset = parse_pagination()
    rows = list_rows("payouts", ["property_id", "status"])
    items, total = paginate(rows, limit, offset)
    return respond_array(items, limit, offset, total)


@app.route("/payouts/<pid>/decision", methods=["POST"])
def payouts_decision(pid):
    caller, _ = authenticate({"PlatformAdmin"})
    payout = get_payout(pid)
    body = get_body()
    decision = require_enum(body, "decision", {"APPROVE", "REJECT"})
    if payout["status"] != "SUBMITTED":
        err("ERR_PAYOUT_INVALID_STATE", "Only a SUBMITTED payout can be decided.")
    prop = DB["properties"].get(payout["property_id"])
    if decision == "APPROVE" and (prop is None or prop["status"] == "SUSPENDED"):
        err("ERR_PROPERTY_NOT_ACTIVE", "Property is suspended.")
    if caller == payout["submitted_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", "Approver must differ from submitter.")
    payout["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    payout["approved_by_user_id"] = caller
    touch(payout)
    return respond_object(public(payout), 200)


@app.route("/payouts/<pid>/pay", methods=["POST"])
def payouts_pay(pid):
    authenticate({"PlatformAdmin"})
    payout = get_payout(pid)
    if payout["status"] != "APPROVED":
        err("ERR_PAYOUT_INVALID_STATE", "Only an APPROVED payout can be paid.")
    payout["status"] = "PAID"
    payout["paid_at"] = clock_stamp()
    touch(payout)
    prop = DB["properties"].get(payout["property_id"])
    if prop is not None:
        recompute_escrow(prop)
    return respond_object(public(payout), 200)


@app.route("/payouts/<pid>/reverse", methods=["POST"])
def payouts_reverse(pid):
    authenticate({"PlatformAdmin"})
    payout = get_payout(pid)
    if payout["status"] != "PAID":
        err("ERR_PAYOUT_INVALID_STATE", "Only a PAID payout can be reversed.")
    payout["status"] = "REVERSED"
    payout["reversed_at"] = clock_stamp()
    touch(payout)
    prop = DB["properties"].get(payout["property_id"])
    if prop is not None:
        recompute_escrow(prop)
    return respond_object(public(payout), 200)


# ROUTES_GO_HERE


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
