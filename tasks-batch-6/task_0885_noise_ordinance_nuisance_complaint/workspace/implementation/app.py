"""
Noise-Ordinance & Nuisance Complaint API (Expert PRD-bench task).

Single-file Flask implementation. In-memory storage only; every process boot
starts with an empty store and a logical clock pinned to 2026-05-01T00:00:00Z.
"""
import os
import math
import uuid
import random
import string
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD §1.3 / constants_index)
# ---------------------------------------------------------------------------
BASE_FINE_CENTS = 10000
MAX_FINE_CENTS = 500000
CHRONIC_FINE_MULTIPLIER = Decimal("1.5")
CHRONIC_WINDOW_DAYS = 365
CHRONIC_WATCH_THRESHOLD = 2
CHRONIC_DESIGNATED_THRESHOLD = 3
ZONING_FINE_FACTOR = {
    "RESIDENTIAL": Decimal("1.0"),
    "COMMERCIAL": Decimal("1.5"),
    "INDUSTRIAL": Decimal("0.75"),
    "MIXED": Decimal("1.25"),
}
PAYMENT_DUE_DAYS = 30
LATE_PENALTY_DAILY_PCT = Decimal("0.015")
CONSTRUCTION_BASE_FEE_CENTS = 5000
CONSTRUCTION_PER_DAY_CENTS = 2500
EVENT_BASE_FEE_CENTS = 10000
EVENT_PER_ATTENDEE_CENTS = 50
VARIANCE_ABSOLUTE_MAX_DB = 95
HEARING_BUFFER_MINUTES = 60
ABATEMENT_COMPLIANCE_DAYS = 30
DEFAULT_CLOCK_UTC = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

ROLES = {"CodeOfficer", "HearingOfficer", "PermitClerk", "Resident", "SystemAdmin"}
ALL_ROLES = set(ROLES)

ZONING_TYPES = {"RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL", "MIXED"}
PERMIT_TYPES = {"CONSTRUCTION", "EVENT"}
NOISE_TYPES = {"CONSTRUCTION", "AMPLIFIED_MUSIC", "MACHINERY", "ANIMAL", "VEHICLE", "OTHER"}
COMPLAINT_SOURCES = {"PHONE", "ONLINE", "OFFICER"}
AGENCIES = {"POLICE", "BUILDING", "HEALTH", "ANIMAL_CONTROL"}
HEARING_OUTCOMES = {"UPHELD", "REDUCED", "DISMISSED", "REMANDED"}
PAYMENT_METHODS = {"CARD", "CHECK", "CASH"}

# ---------------------------------------------------------------------------
# In-memory store (fresh per process — never seeded)
# ---------------------------------------------------------------------------
properties = {}
policies = {}
variances = {}
complaints = {}
inspections = {}
enforcements = {}
hearings = {}
abatements = {}
referrals = {}
payments = {}

CLOCK = {"now": DEFAULT_CLOCK_UTC}
SEQ = {"n": 0}


def next_seq():
    SEQ["n"] += 1
    return SEQ["n"]


def now_dt():
    return CLOCK["now"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_sys(dt):
    """System-generated timestamp: ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------
def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base(extra=None):
    m = {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": fmt_sys(now_dt()),
    }
    if extra:
        m.update(extra)
    return m


def respond(data, response_type="object", code=200, pagination=None):
    body = {
        "meta": meta_base(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), code


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
    }
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


def require(allowed):
    uid, role = authenticate()
    authorize(role, allowed)
    return uid, role


# ---------------------------------------------------------------------------
# Body parsing / field validation
# ---------------------------------------------------------------------------
def get_body():
    b = request.get_json(force=True, silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return b


def _present(body, field):
    return field in body and body[field] is not None


def v_str(body, field, required=True, default=None):
    if not _present(body, field):
        if required:
            raise ApiError("ERR_VALIDATION", 400, "Missing required field: " + field)
        return default
    v = body[field]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, field + " must be a string")
    return v


def v_enum(body, field, allowed, required=True, default=None):
    if not _present(body, field):
        if required:
            raise ApiError("ERR_VALIDATION", 400, "Missing required field: " + field)
        return default
    v = body[field]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, field + " must be a string")
    if v not in allowed:
        raise ApiError("ERR_INVALID_ENUM", 400, field + " has an invalid value")
    return v


def v_int(body, field, required=True, default=None):
    if not _present(body, field):
        if required:
            raise ApiError("ERR_VALIDATION", 400, "Missing required field: " + field)
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, field + " must be an integer")
    return v


def v_number(body, field, required=True, default=None):
    if not _present(body, field):
        if required:
            raise ApiError("ERR_VALIDATION", 400, "Missing required field: " + field)
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 400, field + " must be a number")
    return v


def v_datetime(body, field, required=True, default=None):
    """Return the raw string (echoed verbatim); validates it parses."""
    if not _present(body, field):
        if required:
            raise ApiError("ERR_VALIDATION", 400, "Missing required field: " + field)
        return default
    v = body[field]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, field + " must be an ISO8601 datetime string")
    try:
        parse_iso(v)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, field + " is not a valid ISO8601 datetime")
    return v


def get_or_404(store, id_, error_id):
    r = store.get(id_)
    if r is None:
        raise ApiError(error_id, 404, "Resource not found")
    return r


def fk_exists_or_404(store, value, error_id):
    """For body FK ids: only enforce when a value is supplied."""
    if value is None:
        return
    if value not in store:
        raise ApiError(error_id, 404, "Referenced resource not found")


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------
def new_common(extra):
    now = now_dt()
    rec = {
        "id": str(uuid.uuid4()),
        "_created_dt": now,
        "_updated_dt": now,
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(extra)
    return rec


def new_appendonly(extra):
    rec = {
        "id": str(uuid.uuid4()),
        "_created_dt": now_dt(),
        "_seq": next_seq(),
    }
    rec.update(extra)
    return rec


def touch(rec):
    rec["_updated_dt"] = now_dt()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Pagination + listing
# ---------------------------------------------------------------------------
def paginate(items):
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
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}


def sorted_records(records):
    return sorted(records, key=lambda r: (r["_created_dt"], r["_seq"]))


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_property(p):
    return {
        "id": p["id"],
        "created_at": fmt_sys(p["_created_dt"]),
        "updated_at": fmt_sys(p["_updated_dt"]),
        "version": p["version"],
        "address": p["address"],
        "zoning_type": p["zoning_type"],
        "substantiated_violation_count": p["substantiated_violation_count"],
        "chronic_status": p["chronic_status"],
        "abatement_status": p["abatement_status"],
    }


def ser_policy(p):
    return {
        "id": p["id"],
        "created_at": fmt_sys(p["_created_dt"]),
        "updated_at": fmt_sys(p["_updated_dt"]),
        "version": p["version"],
        "zoning_type": p["zoning_type"],
        "day_limit_db": p["day_limit_db"],
        "night_limit_db": p["night_limit_db"],
        "day_start_hour": p["day_start_hour"],
        "night_start_hour": p["night_start_hour"],
    }


def ser_variance(v):
    return {
        "id": v["id"],
        "created_at": fmt_sys(v["_created_dt"]),
        "updated_at": fmt_sys(v["_updated_dt"]),
        "version": v["version"],
        "property_id": v["property_id"],
        "permit_type": v["permit_type"],
        "requested_start": v["requested_start"],
        "requested_end": v["requested_end"],
        "permitted_max_db": v["permitted_max_db"],
        "expected_attendees": v["expected_attendees"],
        "approved_start": v["approved_start"],
        "approved_end": v["approved_end"],
        "fee_estimate_cents": v["fee_estimate_cents"],
        "fee_final_cents": v["fee_final_cents"],
        "status": v["status"],
    }


def ser_complaint(c):
    return {
        "id": c["id"],
        "created_at": fmt_sys(c["_created_dt"]),
        "updated_at": fmt_sys(c["_updated_dt"]),
        "version": c["version"],
        "property_id": c["property_id"],
        "reported_at": c["reported_at"],
        "noise_type": c["noise_type"],
        "reported_decibel": c["reported_decibel"],
        "source": c["source"],
        "complainant_contact": c["complainant_contact"],
        "status": c["status"],
    }


def ser_inspection(i):
    return {
        "id": i["id"],
        "created_at": fmt_sys(i["_created_dt"]),
        "complaint_id": i["complaint_id"],
        "measured_decibel": i["measured_decibel"],
        "measured_at": i["measured_at"],
        "effective_limit_db": i["effective_limit_db"],
        "exceeds_limit": i["exceeds_limit"],
        "inspected_by_user_id": i["inspected_by_user_id"],
    }


def enforcement_balance(enf):
    paid = 0
    for p in payments.values():
        if p["enforcement_id"] == enf["id"] and p["status"] == "CLEARED":
            if p["kind"] == "PAYMENT":
                paid += p["amount_cents"]
            elif p["kind"] == "REFUND":
                paid -= p["amount_cents"]
    late = late_penalty(enf)
    outstanding = enf["effective_fine_cents"] + late - paid
    return paid, late, outstanding


def late_penalty(enf):
    now = now_dt()
    due = enf["_due_dt"]
    if now <= due:
        return 0
    overdue_days = int((now - due).total_seconds() // 86400)
    if overdue_days <= 0:
        return 0
    per_day = round_half_up(Decimal(enf["effective_fine_cents"]) * LATE_PENALTY_DAILY_PCT)
    return per_day * overdue_days


def ser_enforcement(enf):
    paid, late, outstanding = enforcement_balance(enf)
    return {
        "id": enf["id"],
        "created_at": fmt_sys(enf["_created_dt"]),
        "updated_at": fmt_sys(enf["_updated_dt"]),
        "version": enf["version"],
        "complaint_id": enf["complaint_id"],
        "property_id": enf["property_id"],
        "tier": enf["tier"],
        "escalation_level": enf["escalation_level"],
        "assessed_fine_cents": enf["assessed_fine_cents"],
        "effective_fine_cents": enf["effective_fine_cents"],
        "late_penalty_cents": late,
        "amount_paid_cents": paid,
        "amount_outstanding_cents": outstanding,
        "issued_by_user_id": enf["issued_by_user_id"],
        "issued_at": fmt_sys(enf["_issued_dt"]),
        "due_date": fmt_sys(enf["_due_dt"]),
        "status": enf["status"],
    }


def ser_hearing(h):
    return {
        "id": h["id"],
        "created_at": fmt_sys(h["_created_dt"]),
        "updated_at": fmt_sys(h["_updated_dt"]),
        "version": h["version"],
        "enforcement_id": h["enforcement_id"],
        "hearing_officer_id": h["hearing_officer_id"],
        "scheduled_at": h["scheduled_at"],
        "duration_minutes": h["duration_minutes"],
        "reduction_pct": h["reduction_pct"],
        "outcome": h["outcome"],
        "decided_at": fmt_sys(h["_decided_dt"]) if h["_decided_dt"] is not None else None,
    }


def ser_abatement(a):
    return {
        "id": a["id"],
        "created_at": fmt_sys(a["_created_dt"]),
        "updated_at": fmt_sys(a["_updated_dt"]),
        "version": a["version"],
        "property_id": a["property_id"],
        "enforcement_id": a["enforcement_id"],
        "trigger_source": a["trigger_source"],
        "compliance_deadline": a["compliance_deadline"],
        "status": a["status"],
    }


def ser_referral(r):
    return {
        "id": r["id"],
        "created_at": fmt_sys(r["_created_dt"]),
        "updated_at": fmt_sys(r["_updated_dt"]),
        "version": r["version"],
        "complaint_id": r["complaint_id"],
        "agency": r["agency"],
        "reason": r["reason"],
        "status": r["status"],
    }


def ser_payment(p):
    return {
        "id": p["id"],
        "created_at": fmt_sys(p["_created_dt"]),
        "enforcement_id": p["enforcement_id"],
        "amount_cents": p["amount_cents"],
        "kind": p["kind"],
        "method": p["method"],
        "status": p["status"],
    }


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def within_chronic_window(enf, now):
    return (now - enf["_issued_dt"]).total_seconds() <= CHRONIC_WINDOW_DAYS * 86400


def count_nondismissed_enforcements(property_id, now):
    c = 0
    for e in enforcements.values():
        if e["property_id"] == property_id and e["status"] != "DISMISSED":
            if within_chronic_window(e, now):
                c += 1
    return c


def chronic_status_for_count(count):
    if count >= CHRONIC_DESIGNATED_THRESHOLD:
        return "DESIGNATED"
    if count >= CHRONIC_WATCH_THRESHOLD:
        return "WATCH"
    return "NONE"


def find_policy_for_zoning(zoning_type):
    for p in policies.values():
        if p["zoning_type"] == zoning_type:
            return p
    return None


def variance_fee(permit_type, start_raw, end_raw, attendees):
    if permit_type == "CONSTRUCTION":
        start = parse_iso(start_raw)
        end = parse_iso(end_raw)
        days = math.ceil((end - start).total_seconds() / 86400)
        return CONSTRUCTION_BASE_FEE_CENTS + CONSTRUCTION_PER_DAY_CENTS * days
    else:  # EVENT
        return EVENT_BASE_FEE_CENTS + EVENT_PER_ATTENDEE_CENTS * attendees


# ===========================================================================
# PROPERTY
# ===========================================================================
@app.route("/properties", methods=["POST"])
def create_property():
    require({"CodeOfficer", "SystemAdmin"})
    body = get_body()
    address = v_str(body, "address")
    zoning_type = v_enum(body, "zoning_type", ZONING_TYPES)
    p = new_common({
        "address": address,
        "zoning_type": zoning_type,
        "substantiated_violation_count": 0,
        "chronic_status": "NONE",
        "abatement_status": "NONE",
    })
    properties[p["id"]] = p
    return respond(ser_property(p), "object", 201)


@app.route("/properties", methods=["GET"])
def list_properties():
    require(ALL_ROLES)
    zoning = request.args.get("zoning_type")
    chronic = request.args.get("chronic_status")
    recs = list(properties.values())
    if zoning is not None:
        recs = [r for r in recs if r["zoning_type"] == zoning]
    if chronic is not None:
        recs = [r for r in recs if r["chronic_status"] == chronic]
    recs = sorted_records(recs)
    page, pg = paginate(recs)
    return respond([ser_property(r) for r in page], "array", 200, pg)


@app.route("/properties/<pid>", methods=["GET"])
def get_property(pid):
    require(ALL_ROLES)
    p = get_or_404(properties, pid, "ERR_PROPERTY_NOT_FOUND")
    return respond(ser_property(p), "object", 200)


# ===========================================================================
# NOISE LIMIT POLICY
# ===========================================================================
@app.route("/noise-policies", methods=["POST"])
def create_policy():
    require({"SystemAdmin"})
    body = get_body()
    zoning_type = v_enum(body, "zoning_type", ZONING_TYPES)
    day_limit = v_number(body, "day_limit_db")
    night_limit = v_number(body, "night_limit_db")
    day_start = v_int(body, "day_start_hour")
    night_start = v_int(body, "night_start_hour")
    if not (0 <= day_start <= 23) or not (0 <= night_start <= 23):
        raise ApiError("ERR_VALIDATION", 400, "hour boundaries must be in [0,23]")
    # referential: uniqueness per zoning
    if find_policy_for_zoning(zoning_type) is not None:
        raise ApiError("ERR_DUPLICATE_POLICY", 409, "A policy already exists for this zoning_type")
    p = new_common({
        "zoning_type": zoning_type,
        "day_limit_db": day_limit,
        "night_limit_db": night_limit,
        "day_start_hour": day_start,
        "night_start_hour": night_start,
    })
    policies[p["id"]] = p
    return respond(ser_policy(p), "object", 201)


@app.route("/noise-policies", methods=["GET"])
def list_policies():
    require(ALL_ROLES)
    zoning = request.args.get("zoning_type")
    recs = list(policies.values())
    if zoning is not None:
        recs = [r for r in recs if r["zoning_type"] == zoning]
    recs = sorted_records(recs)
    page, pg = paginate(recs)
    return respond([ser_policy(r) for r in page], "array", 200, pg)


# ===========================================================================
# VARIANCE PERMIT
# ===========================================================================
@app.route("/variance-permits", methods=["POST"])
def create_variance():
    require({"Resident", "PermitClerk"})
    body = get_body()
    # existence (body FK) before well-formedness
    fk_exists_or_404(properties, body.get("property_id"), "ERR_PROPERTY_NOT_FOUND")
    property_id = v_str(body, "property_id")
    permit_type = v_enum(body, "permit_type", PERMIT_TYPES)
    requested_start = v_datetime(body, "requested_start")
    requested_end = v_datetime(body, "requested_end")
    permitted_max_db = v_number(body, "permitted_max_db")
    expected_attendees = v_int(body, "expected_attendees", required=False, default=0)
    # window well-formedness
    if parse_iso(requested_end) <= parse_iso(requested_start):
        raise ApiError("ERR_INVALID_WINDOW", 400, "requested_end must be strictly after requested_start")
    fee_estimate = variance_fee(permit_type, requested_start, requested_end, expected_attendees)
    v = new_common({
        "property_id": property_id,
        "permit_type": permit_type,
        "requested_start": requested_start,
        "requested_end": requested_end,
        "permitted_max_db": permitted_max_db,
        "expected_attendees": expected_attendees,
        "approved_start": None,
        "approved_end": None,
        "fee_estimate_cents": fee_estimate,
        "fee_final_cents": None,
        "status": "UNDER_REVIEW",
    })
    variances[v["id"]] = v
    return respond(ser_variance(v), "object", 201)


@app.route("/variance-permits", methods=["GET"])
def list_variances():
    require(ALL_ROLES)
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    permit_type = request.args.get("permit_type")
    recs = list(variances.values())
    if property_id is not None:
        recs = [r for r in recs if r["property_id"] == property_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    if permit_type is not None:
        recs = [r for r in recs if r["permit_type"] == permit_type]
    recs = sorted_records(recs)
    page, pg = paginate(recs)
    return respond([ser_variance(r) for r in page], "array", 200, pg)


@app.route("/variance-permits/<vid>", methods=["GET"])
def get_variance(vid):
    require(ALL_ROLES)
    v = get_or_404(variances, vid, "ERR_VARIANCE_NOT_FOUND")
    return respond(ser_variance(v), "object", 200)


@app.route("/variance-permits/<vid>/issue", methods=["POST"])
def issue_variance(vid):
    require({"PermitClerk"})
    v = get_or_404(variances, vid, "ERR_VARIANCE_NOT_FOUND")
    body = get_body()
    approved_start = v_datetime(body, "approved_start", required=False, default=None)
    approved_end = v_datetime(body, "approved_end", required=False, default=None)
    permitted_override = v_number(body, "permitted_max_db", required=False, default=None)

    eff_start = approved_start if approved_start is not None else v["requested_start"]
    eff_end = approved_end if approved_end is not None else v["requested_end"]
    # (4) window well-formedness
    if parse_iso(eff_end) <= parse_iso(eff_start):
        raise ApiError("ERR_INVALID_WINDOW", 400, "approved_end must be strictly after approved_start")
    # (5) state
    if v["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_VARIANCE_NOT_UNDER_REVIEW", 409, "Variance is not UNDER_REVIEW")
    permitted = permitted_override if permitted_override is not None else v["permitted_max_db"]
    # (8) temporal: overlap with other ISSUED variances on same property (half-open)
    s1 = parse_iso(eff_start)
    e1 = parse_iso(eff_end)
    for other in variances.values():
        if other["id"] == v["id"]:
            continue
        if other["property_id"] != v["property_id"]:
            continue
        if other["status"] != "ISSUED":
            continue
        s2 = parse_iso(other["approved_start"])
        e2 = parse_iso(other["approved_end"])
        if s1 < e2 and s2 < e1:
            raise ApiError("ERR_VARIANCE_WINDOW_OVERLAP", 409, "Overlaps another ISSUED variance window")
    # (10) domain threshold: db cap
    if permitted > VARIANCE_ABSOLUTE_MAX_DB:
        raise ApiError("ERR_VARIANCE_DB_EXCEEDS_CAP", 422, "permitted_max_db exceeds the absolute cap")

    v["approved_start"] = eff_start
    v["approved_end"] = eff_end
    v["permitted_max_db"] = permitted
    v["fee_final_cents"] = variance_fee(v["permit_type"], eff_start, eff_end, v["expected_attendees"])
    v["status"] = "ISSUED"
    touch(v)
    return respond(ser_variance(v), "object", 200)


@app.route("/variance-permits/<vid>/deny", methods=["POST"])
def deny_variance(vid):
    require({"PermitClerk"})
    v = get_or_404(variances, vid, "ERR_VARIANCE_NOT_FOUND")
    get_body()
    if v["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_VARIANCE_NOT_UNDER_REVIEW", 409, "Variance is not UNDER_REVIEW")
    v["status"] = "DENIED"
    touch(v)
    return respond(ser_variance(v), "object", 200)


@app.route("/variance-permits/<vid>/revoke", methods=["POST"])
def revoke_variance(vid):
    require({"PermitClerk"})
    v = get_or_404(variances, vid, "ERR_VARIANCE_NOT_FOUND")
    get_body()
    if v["status"] != "ISSUED":
        raise ApiError("ERR_VARIANCE_NOT_ISSUED", 409, "Variance is not ISSUED")
    v["status"] = "REVOKED"
    touch(v)
    return respond(ser_variance(v), "object", 200)


# ===========================================================================
# COMPLAINT
# ===========================================================================
@app.route("/complaints", methods=["POST"])
def create_complaint():
    require({"Resident", "CodeOfficer"})
    body = get_body()
    fk_exists_or_404(properties, body.get("property_id"), "ERR_PROPERTY_NOT_FOUND")
    property_id = v_str(body, "property_id")
    reported_at = v_datetime(body, "reported_at")
    noise_type = v_enum(body, "noise_type", NOISE_TYPES)
    reported_decibel = v_number(body, "reported_decibel", required=False, default=None)
    source = v_enum(body, "source", COMPLAINT_SOURCES, required=False, default="PHONE")
    complainant_contact = v_str(body, "complainant_contact", required=False, default=None)
    c = new_common({
        "property_id": property_id,
        "reported_at": reported_at,
        "noise_type": noise_type,
        "reported_decibel": reported_decibel,
        "source": source,
        "complainant_contact": complainant_contact,
        "status": "RECEIVED",
    })
    complaints[c["id"]] = c
    return respond(ser_complaint(c), "object", 201)


@app.route("/complaints", methods=["GET"])
def list_complaints():
    require(ALL_ROLES)
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    recs = list(complaints.values())
    if property_id is not None:
        recs = [r for r in recs if r["property_id"] == property_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    recs = sorted_records(recs)
    page, pg = paginate(recs)
    return respond([ser_complaint(r) for r in page], "array", 200, pg)


@app.route("/complaints/<cid>", methods=["GET"])
def get_complaint(cid):
    require(ALL_ROLES)
    c = get_or_404(complaints, cid, "ERR_COMPLAINT_NOT_FOUND")
    return respond(ser_complaint(c), "object", 200)


@app.route("/complaints/<cid>/review", methods=["POST"])
def review_complaint(cid):
    require({"CodeOfficer"})
    c = get_or_404(complaints, cid, "ERR_COMPLAINT_NOT_FOUND")
    get_body()
    if c["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Complaint is not RECEIVED")
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return respond(ser_complaint(c), "object", 200)


@app.route("/complaints/<cid>/inspections", methods=["POST"])
def create_inspection(cid):
    uid, role = require({"CodeOfficer"})
    c = get_or_404(complaints, cid, "ERR_COMPLAINT_NOT_FOUND")
    body = get_body()
    measured_decibel = v_number(body, "measured_decibel")
    measured_at = v_datetime(body, "measured_at")
    # referential: policy configured for property zoning
    prop = properties.get(c["property_id"])
    policy = find_policy_for_zoning(prop["zoning_type"]) if prop else None
    if policy is None:
        raise ApiError("ERR_POLICY_NOT_CONFIGURED", 409, "No policy configured for the property's zoning")
    hour = parse_iso(measured_at).hour
    if policy["day_start_hour"] <= hour < policy["night_start_hour"]:
        effective_limit = policy["day_limit_db"]
    else:
        effective_limit = policy["night_limit_db"]
    exceeds = measured_decibel > effective_limit
    ins = new_appendonly({
        "complaint_id": cid,
        "measured_decibel": measured_decibel,
        "measured_at": measured_at,
        "effective_limit_db": effective_limit,
        "exceeds_limit": exceeds,
        "inspected_by_user_id": uid,
    })
    inspections[ins["id"]] = ins
    return respond(ser_inspection(ins), "object", 201)


@app.route("/complaints/<cid>/inspections", methods=["GET"])
def list_inspections(cid):
    require(ALL_ROLES)
    get_or_404(complaints, cid, "ERR_COMPLAINT_NOT_FOUND")
    recs = [r for r in inspections.values() if r["complaint_id"] == cid]
    recs = sorted_records(recs)
    page, pg = paginate(recs)
    return respond([ser_inspection(r) for r in page], "array", 200, pg)


def latest_inspection_for(cid):
    recs = [r for r in inspections.values() if r["complaint_id"] == cid]
    if not recs:
        return None
    recs = sorted_records(recs)
    return recs[-1]


@app.route("/complaints/<cid>/substantiate", methods=["POST"])
def substantiate_complaint(cid):
    uid, role = require({"CodeOfficer"})
    c = get_or_404(complaints, cid, "ERR_COMPLAINT_NOT_FOUND")
    get_body()
    # (5) state
    if c["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_COMPLAINT_NOT_UNDER_REVIEW", 409, "Complaint is not UNDER_REVIEW")
    # (10) domain: inspection on record
    latest = latest_inspection_for(cid)
    if latest is None:
        raise ApiError("ERR_NO_INSPECTION_ON_RECORD", 422, "No inspection recorded for this complaint")
    # (10) domain: latest inspection exceeds limit
    if not latest["exceeds_limit"]:
        raise ApiError("ERR_NOISE_WITHIN_LIMIT", 422, "Latest inspection did not exceed the limit")
    # (8) temporal: covering ISSUED variance blocks substantiation
    prop = properties.get(c["property_id"])
    reported_dt = parse_iso(c["reported_at"])
    measured = latest["measured_decibel"]
    for vp in variances.values():
        if vp["status"] != "ISSUED":
            continue
        if vp["property_id"] != c["property_id"]:
            continue
        if vp["approved_start"] is None or vp["approved_end"] is None:
            continue
        a_s = parse_iso(vp["approved_start"])
        a_e = parse_iso(vp["approved_end"])
        if a_s <= reported_dt < a_e and vp["permitted_max_db"] >= measured:
            raise ApiError("ERR_VARIANCE_COVERS_COMPLAINT", 409, "An issued variance covers this complaint")

    now = now_dt()
    # Cascade hop 1: create enforcement
    level = count_nondismissed_enforcements(c["property_id"], now)
    zoning = prop["zoning_type"]
    chronic_before = prop["chronic_status"]
    if level == 0:
        tier = "WARNING"
        assessed = 0
    else:
        tier = "CITATION"
        chronic_factor = CHRONIC_FINE_MULTIPLIER if chronic_before == "DESIGNATED" else Decimal("1")
        raw = Decimal(BASE_FINE_CENTS) * Decimal(level) * ZONING_FINE_FACTOR[zoning] * chronic_factor
        assessed = min(MAX_FINE_CENTS, round_half_up(raw))
    enf = new_common({
        "complaint_id": cid,
        "property_id": c["property_id"],
        "tier": tier,
        "escalation_level": level,
        "assessed_fine_cents": assessed,
        "effective_fine_cents": assessed,
        "issued_by_user_id": uid,
        "_issued_dt": now,
        "_due_dt": now + timedelta(days=PAYMENT_DUE_DAYS),
        "status": "ISSUED",
    })
    enforcements[enf["id"]] = enf

    # complaint transition
    c["status"] = "SUBSTANTIATED"
    touch(c)

    # Cascade hop 2: property count + chronic recompute
    count = count_nondismissed_enforcements(c["property_id"], now)
    prop["substantiated_violation_count"] = count
    new_chronic = chronic_status_for_count(count)
    prop["chronic_status"] = new_chronic
    # Cascade hop 3: auto abatement when newly DESIGNATED
    if new_chronic == "DESIGNATED" and chronic_before != "DESIGNATED":
        ab = new_common({
            "property_id": c["property_id"],
            "enforcement_id": None,
            "trigger_source": "CHRONIC_DESIGNATION",
            "compliance_deadline": fmt_sys(now + timedelta(days=ABATEMENT_COMPLIANCE_DAYS)),
            "status": "PENDING",
        })
        abatements[ab["id"]] = ab
        prop["abatement_status"] = "UNDER_ABATEMENT"
    touch(prop)

    return respond(ser_enforcement(enf), "object", 201)


@app.route("/complaints/<cid>/dismiss", methods=["POST"])
def dismiss_complaint(cid):
    require({"CodeOfficer"})
    c = get_or_404(complaints, cid, "ERR_COMPLAINT_NOT_FOUND")
    get_body()
    if c["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_COMPLAINT_NOT_UNDER_REVIEW", 409, "Complaint is not UNDER_REVIEW")
    c["status"] = "DISMISSED"
    touch(c)
    return respond(ser_complaint(c), "object", 200)


# ===========================================================================
# CROSS-AGENCY REFERRAL
# ===========================================================================
@app.route("/referrals", methods=["POST"])
def create_referral():
    require({"CodeOfficer"})
    body = get_body()
    fk_exists_or_404(complaints, body.get("complaint_id"), "ERR_COMPLAINT_NOT_FOUND")
    complaint_id = v_str(body, "complaint_id")
    agency = v_enum(body, "agency", AGENCIES)
    reason = v_str(body, "reason", required=False, default=None)
    r = new_common({
        "complaint_id": complaint_id,
        "agency": agency,
        "reason": reason,
        "status": "OPEN",
    })
    referrals[r["id"]] = r
    return respond(ser_referral(r), "object", 201)


@app.route("/referrals", methods=["GET"])
def list_referrals():
    require(ALL_ROLES)
    complaint_id = request.args.get("complaint_id")
    status = request.args.get("status")
    recs = list(referrals.values())
    if complaint_id is not None:
        recs = [r for r in recs if r["complaint_id"] == complaint_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    recs = sorted_records(recs)
    page, pg = paginate(recs)
    return respond([ser_referral(r) for r in page], "array", 200, pg)


@app.route("/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    require(ALL_ROLES)
    r = get_or_404(referrals, rid, "ERR_REFERRAL_NOT_FOUND")
    return respond(ser_referral(r), "object", 200)


@app.route("/referrals/<rid>/acknowledge", methods=["POST"])
def acknowledge_referral(rid):
    require({"CodeOfficer"})
    r = get_or_404(referrals, rid, "ERR_REFERRAL_NOT_FOUND")
    get_body()
    if r["status"] != "OPEN":
        raise ApiError("ERR_REFERRAL_INVALID_STATE", 409, "Referral is not OPEN")
    r["status"] = "ACKNOWLEDGED"
    touch(r)
    return respond(ser_referral(r), "object", 200)


@app.route("/referrals/<rid>/close", methods=["POST"])
def close_referral(rid):
    require({"CodeOfficer"})
    r = get_or_404(referrals, rid, "ERR_REFERRAL_NOT_FOUND")
    get_body()
    if r["status"] not in ("OPEN", "ACKNOWLEDGED"):
        raise ApiError("ERR_REFERRAL_INVALID_STATE", 409, "Referral cannot be closed from its current state")
    r["status"] = "CLOSED"
    touch(r)
    return respond(ser_referral(r), "object", 200)


# ===========================================================================
# ENFORCEMENT
# ===========================================================================
@app.route("/enforcements", methods=["GET"])
def list_enforcements():
    require(ALL_ROLES)
    complaint_id = request.args.get("complaint_id")
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    tier = request.args.get("tier")
    recs = list(enforcements.values())
    if complaint_id is not None:
        recs = [r for r in recs if r["complaint_id"] == complaint_id]
    if property_id is not None:
        recs = [r for r in recs if r["property_id"] == property_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    if tier is not None:
        recs = [r for r in recs if r["tier"] == tier]
    recs = sorted_records(recs)
    page, pg = paginate(recs)
    return respond([ser_enforcement(r) for r in page], "array", 200, pg)


@app.route("/enforcements/<eid>", methods=["GET"])
def get_enforcement(eid):
    require(ALL_ROLES)
    e = get_or_404(enforcements, eid, "ERR_ENFORCEMENT_NOT_FOUND")
    return respond(ser_enforcement(e), "object", 200)


@app.route("/enforcements/<eid>/contest", methods=["POST"])
def contest_enforcement(eid):
    require({"Resident"})
    e = get_or_404(enforcements, eid, "ERR_ENFORCEMENT_NOT_FOUND")
    get_body()
    if e["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Enforcement is not ISSUED")
    if e["tier"] != "CITATION":
        raise ApiError("ERR_ENFORCEMENT_NOT_CITATION", 409, "Only a CITATION may be contested")
    e["status"] = "CONTESTED"
    touch(e)
    return respond(ser_enforcement(e), "object", 200)


@app.route("/enforcements/<eid>/hearings", methods=["POST"])
def schedule_hearing(eid):
    require({"HearingOfficer"})
    e = get_or_404(enforcements, eid, "ERR_ENFORCEMENT_NOT_FOUND")
    body = get_body()
    scheduled_at = v_datetime(body, "scheduled_at")
    hearing_officer_id = v_str(body, "hearing_officer_id")
    duration_minutes = v_int(body, "duration_minutes", required=False, default=30)
    # (5) state
    if e["status"] != "CONTESTED":
        raise ApiError("ERR_ENFORCEMENT_NOT_CONTESTED", 409, "Enforcement is not CONTESTED")
    # (8) temporal: per-officer slot buffer
    s1 = parse_iso(scheduled_at)
    e1 = s1 + timedelta(minutes=duration_minutes)
    buffer_seconds = HEARING_BUFFER_MINUTES * 60
    for h in hearings.values():
        if h["hearing_officer_id"] != hearing_officer_id:
            continue
        s2 = parse_iso(h["scheduled_at"])
        e2 = s2 + timedelta(minutes=h["duration_minutes"])
        # gap between closed intervals; conflict if strictly within buffer
        if s1 <= e2 and s2 <= e1:
            gap = 0.0
        elif s1 > e2:
            gap = (s1 - e2).total_seconds()
        else:
            gap = (s2 - e1).total_seconds()
        if gap < buffer_seconds:
            raise ApiError("ERR_HEARING_SLOT_CONFLICT", 409, "Officer has a conflicting hearing slot")

    h = new_common({
        "enforcement_id": eid,
        "hearing_officer_id": hearing_officer_id,
        "scheduled_at": scheduled_at,
        "duration_minutes": duration_minutes,
        "reduction_pct": None,
        "outcome": "PENDING",
        "_decided_dt": None,
    })
    hearings[h["id"]] = h
    e["status"] = "HEARING_SCHEDULED"
    touch(e)
    return respond(ser_hearing(h), "object", 201)


@app.route("/enforcements/<eid>/hearings", methods=["GET"])
def list_hearings(eid):
    require(ALL_ROLES)
    get_or_404(enforcements, eid, "ERR_ENFORCEMENT_NOT_FOUND")
    recs = [r for r in hearings.values() if r["enforcement_id"] == eid]
    recs = sorted_records(recs)
    page, pg = paginate(recs)
    return respond([ser_hearing(r) for r in page], "array", 200, pg)


@app.route("/enforcements/<eid>/payments", methods=["POST"])
def record_payment(eid):
    require({"Resident"})
    e = get_or_404(enforcements, eid, "ERR_ENFORCEMENT_NOT_FOUND")
    body = get_body()
    amount_cents = v_int(body, "amount_cents")
    expected_version = v_int(body, "expected_enforcement_version")
    method = v_enum(body, "method", PAYMENT_METHODS, required=False, default="CARD")
    if amount_cents <= 0:
        raise ApiError("ERR_VALIDATION", 400, "amount_cents must be a positive integer")
    # (6) OCC
    if expected_version != e["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_enforcement_version does not match")
    # (11) fiscal
    paid, late, outstanding = enforcement_balance(e)
    if amount_cents > outstanding:
        raise ApiError("ERR_PAYMENT_EXCEEDS_OUTSTANDING", 402, "Payment exceeds outstanding balance")

    p = new_appendonly({
        "enforcement_id": eid,
        "amount_cents": amount_cents,
        "kind": "PAYMENT",
        "method": method,
        "status": "CLEARED",
    })
    payments[p["id"]] = p
    touch(e)
    # auto -> PAID
    _, _, outstanding_after = enforcement_balance(e)
    if outstanding_after <= 0 and e["status"] in ("ISSUED", "UPHELD", "REDUCED"):
        e["status"] = "PAID"
    return respond(ser_payment(p), "object", 201)


@app.route("/enforcements/<eid>/payments", methods=["GET"])
def list_payments(eid):
    require(ALL_ROLES)
    get_or_404(enforcements, eid, "ERR_ENFORCEMENT_NOT_FOUND")
    recs = [r for r in payments.values() if r["enforcement_id"] == eid]
    recs = sorted_records(recs)
    page, pg = paginate(recs)
    return respond([ser_payment(r) for r in page], "array", 200, pg)


# ===========================================================================
# HEARING DECIDE
# ===========================================================================
@app.route("/hearings/<hid>/decide", methods=["POST"])
def decide_hearing(hid):
    uid, role = require({"HearingOfficer"})
    h = get_or_404(hearings, hid, "ERR_HEARING_NOT_FOUND")
    body = get_body()
    outcome = v_enum(body, "outcome", HEARING_OUTCOMES)
    # reduction_pct type check only when supplied (range checked at domain step)
    reduction_pct = None
    if _present(body, "reduction_pct"):
        reduction_pct = v_number(body, "reduction_pct", required=False, default=None)
    e = enforcements[h["enforcement_id"]]
    # (5) state
    if h["outcome"] != "PENDING":
        raise ApiError("ERR_HEARING_NOT_PENDING", 409, "Hearing is not PENDING")
    # (9) segregation of duties
    if uid == e["issued_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403, "Decider must differ from the issuing officer")
    # (10) domain: reduction range for REDUCED
    if outcome == "REDUCED":
        if reduction_pct is None or not (0 <= reduction_pct < 1):
            raise ApiError("ERR_REDUCTION_PCT_INVALID", 422, "reduction_pct must be in [0,1)")

    now = now_dt()
    h["_decided_dt"] = now

    if outcome == "UPHELD":
        h["outcome"] = "UPHELD"
        e["status"] = "UPHELD"
        touch(h)
        touch(e)
    elif outcome == "REDUCED":
        h["outcome"] = "REDUCED"
        h["reduction_pct"] = reduction_pct
        new_effective = round_half_up(Decimal(e["assessed_fine_cents"]) * (Decimal("1") - Decimal(str(reduction_pct))))
        e["effective_fine_cents"] = new_effective
        e["status"] = "REDUCED"
        touch(h)
        touch(e)
        # refund surplus if overpaid
        paid, late, _ = enforcement_balance(e)
        if paid > new_effective + late:
            surplus = paid - (new_effective + late)
            rp = new_appendonly({
                "enforcement_id": e["id"],
                "amount_cents": surplus,
                "kind": "REFUND",
                "method": "CARD",
                "status": "CLEARED",
            })
            payments[rp["id"]] = rp
    elif outcome == "DISMISSED":
        h["outcome"] = "DISMISSED"
        e["status"] = "DISMISSED"
        touch(h)
        # full refund of any paid amount (computed before decrement cascade)
        paid, late, _ = enforcement_balance(e)
        if paid > 0:
            rp = new_appendonly({
                "enforcement_id": e["id"],
                "amount_cents": paid,
                "kind": "REFUND",
                "method": "CARD",
                "status": "CLEARED",
            })
            payments[rp["id"]] = rp
        touch(e)
        # property chronic recompute (enforcement now DISMISSED, excluded)
        prop = properties[e["property_id"]]
        chronic_before = prop["chronic_status"]
        count = count_nondismissed_enforcements(e["property_id"], now)
        prop["substantiated_violation_count"] = count
        new_chronic = chronic_status_for_count(count)
        prop["chronic_status"] = new_chronic
        if count < CHRONIC_DESIGNATED_THRESHOLD:
            for ab in abatements.values():
                if (ab["property_id"] == e["property_id"] and ab["status"] == "PENDING"
                        and ab["trigger_source"] == "CHRONIC_DESIGNATION"):
                    ab["status"] = "VACATED"
                    touch(ab)
                    prop["abatement_status"] = "NONE"
        touch(prop)
    elif outcome == "REMANDED":
        h["outcome"] = "REMANDED"
        e["status"] = "CONTESTED"
        touch(h)
        touch(e)

    return respond(ser_hearing(h), "object", 200)


# ===========================================================================
# ABATEMENT ORDER
# ===========================================================================
@app.route("/abatement-orders", methods=["POST"])
def create_abatement():
    require({"CodeOfficer"})
    body = get_body()
    # (3) existence of body FKs
    fk_exists_or_404(properties, body.get("property_id"), "ERR_PROPERTY_NOT_FOUND")
    fk_exists_or_404(enforcements, body.get("enforcement_id"), "ERR_ENFORCEMENT_NOT_FOUND")
    # (4) well-formedness
    property_id = v_str(body, "property_id")
    expected_version = v_int(body, "expected_property_version")
    enforcement_id = v_str(body, "enforcement_id", required=False, default=None)
    compliance_deadline = v_datetime(body, "compliance_deadline", required=False, default=None)
    prop = properties[property_id]
    # (6) OCC
    if expected_version != prop["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_property_version does not match")
    # (7) referential: enforcement belongs to property
    if enforcement_id is not None:
        if enforcements[enforcement_id]["property_id"] != property_id:
            raise ApiError("ERR_ENFORCEMENT_PROPERTY_MISMATCH", 409, "Enforcement does not belong to property")

    now = now_dt()
    if compliance_deadline is None:
        compliance_deadline = fmt_sys(now + timedelta(days=ABATEMENT_COMPLIANCE_DAYS))
    ab = new_common({
        "property_id": property_id,
        "enforcement_id": enforcement_id,
        "trigger_source": "DELINQUENT_CITATION",
        "compliance_deadline": compliance_deadline,
        "status": "PENDING",
    })
    abatements[ab["id"]] = ab
    prop["abatement_status"] = "UNDER_ABATEMENT"
    touch(prop)
    return respond(ser_abatement(ab), "object", 201)


@app.route("/abatement-orders", methods=["GET"])
def list_abatements():
    require(ALL_ROLES)
    property_id = request.args.get("property_id")
    enforcement_id = request.args.get("enforcement_id")
    status = request.args.get("status")
    recs = list(abatements.values())
    if property_id is not None:
        recs = [r for r in recs if r["property_id"] == property_id]
    if enforcement_id is not None:
        recs = [r for r in recs if r["enforcement_id"] == enforcement_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    recs = sorted_records(recs)
    page, pg = paginate(recs)
    return respond([ser_abatement(r) for r in page], "array", 200, pg)


@app.route("/abatement-orders/<aid>", methods=["GET"])
def get_abatement(aid):
    require(ALL_ROLES)
    a = get_or_404(abatements, aid, "ERR_ABATEMENT_NOT_FOUND")
    return respond(ser_abatement(a), "object", 200)


@app.route("/abatement-orders/<aid>/comply", methods=["POST"])
def comply_abatement(aid):
    require({"CodeOfficer"})
    a = get_or_404(abatements, aid, "ERR_ABATEMENT_NOT_FOUND")
    get_body()
    if a["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Abatement order is not PENDING")
    prop = properties[a["property_id"]]
    if prop["abatement_status"] != "UNDER_ABATEMENT":
        raise ApiError("ERR_PROPERTY_NOT_UNDER_ABATEMENT", 409, "Property is not UNDER_ABATEMENT")
    a["status"] = "COMPLIED"
    touch(a)
    prop["abatement_status"] = "ABATED"
    touch(prop)
    return respond(ser_abatement(a), "object", 200)


@app.route("/abatement-orders/<aid>/escalate", methods=["POST"])
def escalate_abatement(aid):
    require({"CodeOfficer"})
    a = get_or_404(abatements, aid, "ERR_ABATEMENT_NOT_FOUND")
    get_body()
    if a["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Abatement order is not PENDING")
    deadline = parse_iso(a["compliance_deadline"])
    if now_dt() < deadline:
        raise ApiError("ERR_ABATEMENT_DEADLINE_NOT_REACHED", 409, "Compliance deadline not yet reached")
    a["status"] = "ESCALATED"
    touch(a)
    return respond(ser_abatement(a), "object", 200)


# ===========================================================================
# LOGICAL CLOCK
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require({"SystemAdmin"})
    body = get_body()
    to_iso = v_datetime(body, "to_iso8601")
    CLOCK["now"] = parse_iso(to_iso)
    return respond({}, "object", 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
