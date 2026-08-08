import os
import re
import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# In-memory store (empty on every boot; no seeding)
# =============================================================================
DB = {
    "participants": {},
    "sites": {},
    "insurance_policies": {},
    "supervisors": {},
    "referrals": {},
    "placements": {},
    "work_sessions": {},
    "fee_conversions": {},
    "compliance_actions": {},
    "certificates": {},
}
SEQ = 0
CERT_SEQ = 0

# Logical clock -------------------------------------------------------------
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"


def _parse(s):
    """Parse an ISO-8601 string to an aware UTC datetime, or raise ValueError."""
    if not isinstance(s, str) or not s.strip():
        raise ValueError("bad datetime")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


CLOCK_RAW = CLOCK_DEFAULT
CLOCK_DT = _parse(CLOCK_DEFAULT)

ROLES = {"CourtClerk", "ProgramCoordinator", "SiteSupervisor", "Participant"}

# Fee-conversion constants
BASE_CONVERSION_RATE_CENTS = Decimal(1500)
INDIGENCY_MULTIPLIER = {"NONE": Decimal("1.0"), "PARTIAL": Decimal("0.5"), "FULL": Decimal("0.25")}
MIN_FEE_CENTS = Decimal(2500)
MAX_FEE_CENTS = Decimal(200000)
QUARTER = Decimal("0.25")
REST_BUFFER_MINUTES = 60

ENUMS = {
    "risk_level": {"LOW", "MEDIUM", "HIGH"},
    "agency_type": {"NONPROFIT", "GOVERNMENT", "FAITH_BASED", "OTHER"},
    "offense_class": {"INFRACTION", "MISDEMEANOR", "FELONY"},
    "indigency_status": {"NONE", "PARTIAL", "FULL"},
    "session_category": {"STANDARD", "WEEKEND_CREW", "ALTERNATIVE"},
    "action_type": {"WARNING", "REPORT_BACK"},
    "verify_outcome": {"VERIFIED", "DISPUTED", "REJECTED"},
}


# =============================================================================
# Errors & response envelope
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _canonical3(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _meta(extra=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": _canonical3(CLOCK_DT)}
    if extra:
        m.update(extra)
    return m


def _serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def ok(data, response_type="object", status=200, pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def _nf(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def _mna(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"}}
    return jsonify(body), 404


# =============================================================================
# Auth helpers
# =============================================================================
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


# =============================================================================
# Record helpers
# =============================================================================
def create(kind, fields, common=True):
    global SEQ
    rid = str(uuid.uuid4())
    ca = _canonical3(CLOCK_DT)
    rec = {"id": rid, "created_at": ca}
    if common:
        rec["updated_at"] = ca
        rec["version"] = 1
    rec.update(fields)
    SEQ += 1
    rec["_seq"] = SEQ
    DB[kind][rid] = rec
    return rec


def touch(rec):
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = _canonical3(CLOCK_DT)


def get_or_404(kind, rid):
    rec = DB[kind].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "%s not found" % kind)
    return rec


# =============================================================================
# Validation helpers
# =============================================================================
def body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def v_err(msg="Validation failed"):
    raise ApiError("ERR_VALIDATION", 400, msg)


def req_str(b, key):
    v = b.get(key)
    if not isinstance(v, str) or v == "":
        v_err("Field '%s' must be a non-empty string" % key)
    return v


def opt_str(b, key, default=None):
    if key not in b or b[key] is None:
        return default
    v = b[key]
    if not isinstance(v, str) or v == "":
        v_err("Field '%s' must be a non-empty string" % key)
    return v


def req_enum(b, key, enum_key):
    v = req_str(b, key)
    if v not in ENUMS[enum_key]:
        v_err("Field '%s' has an invalid value" % key)
    return v


def opt_enum(b, key, enum_key, default):
    if key not in b or b[key] is None:
        return default
    v = b[key]
    if not isinstance(v, str) or v not in ENUMS[enum_key]:
        v_err("Field '%s' has an invalid value" % key)
    return v


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(b, key, minimum=None):
    v = b.get(key)
    if not is_int(v):
        v_err("Field '%s' must be an integer" % key)
    if minimum is not None and v < minimum:
        v_err("Field '%s' must be >= %s" % (key, minimum))
    return v


def is_quarter_hours(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    if v <= 0:
        return False
    try:
        d = Decimal(str(v))
    except Exception:
        return False
    return (d % QUARTER) == 0


def req_hours(b, key):
    v = b.get(key)
    if not is_quarter_hours(v):
        v_err("Field '%s' must be a positive multiple of 0.25" % key)
    return v


def req_datetime(b, key):
    v = b.get(key)
    if not isinstance(v, str):
        v_err("Field '%s' must be an ISO-8601 datetime string" % key)
    try:
        _parse(v)
    except Exception:
        v_err("Field '%s' is not a valid ISO-8601 datetime" % key)
    return v


def opt_datetime(b, key):
    if key not in b or b[key] is None:
        return None
    return req_datetime(b, key)


# =============================================================================
# Pagination
# =============================================================================
def paginate(items):
    args = request.args
    limit_raw = args.get("limit", "10")
    offset_raw = args.get("offset", "0")
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_PAGINATION_INVALID", 400, "limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError("ERR_PAGINATION_INVALID", 400, "limit must be 1..100 and offset >= 0")
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    pag = {"limit": limit, "offset": offset, "total_count": total,
           "has_more": offset + limit < total}
    return [_serialize(r) for r in window], pag


def list_response(items):
    data, pag = paginate(items)
    return ok(data, response_type="array", status=200, pagination=pag)


# =============================================================================
# Domain helpers
# =============================================================================
def round_quarter(x):
    q = (Decimal(str(x)) / QUARTER).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(q * QUARTER)


def conversion_fee(hours, tier):
    rate = BASE_CONVERSION_RATE_CENTS * INDIGENCY_MULTIPLIER[tier]
    raw = (Decimal(str(hours)) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    fee = min(MAX_FEE_CENTS, max(MIN_FEE_CENTS, raw))
    return int(fee)


def has_valid_insurance(site):
    for p in DB["insurance_policies"].values():
        if p["site_id"] == site["id"] and p["status"] == "VERIFIED":
            try:
                if _parse(p["expiry_date"]) > CLOCK_DT:
                    return True
            except Exception:
                continue
    return False


def recompute_ledger(R):
    hc = 0.0
    for ws in DB["work_sessions"].values():
        if (ws.get("_referral_id") == R["id"]
                and ws["verification_status"] == "VERIFIED"
                and ws["attendance_status"] != "VOIDED"
                and ws.get("verified_hours") is not None):
            hc += ws["verified_hours"]
    conv = 0.0
    fees = 0
    for fc in DB["fee_conversions"].values():
        if fc["referral_id"] == R["id"] and fc["status"] == "PAID":
            conv += fc.get("settled_hours") or 0.0
            fees += fc.get("settlement_fee_cents") or 0
    R["hours_completed"] = hc
    R["hours_converted"] = conv
    R["fees_settled_cents"] = fees
    outstanding = float(R["hours_ordered"]) - hc - conv
    R["hours_outstanding"] = outstanding if outstanding > 0 else 0.0


def mint_certificate(R):
    global CERT_SEQ
    CERT_SEQ += 1
    number = "CERT-%06d" % CERT_SEQ
    total = R["hours_completed"] + R["hours_converted"]
    cert = create("certificates", {
        "referral_id": R["id"],
        "certificate_number": number,
        "total_hours_credited": total,
        "issued_at": CLOCK_RAW,
    }, common=False)
    R["certificate_id"] = cert["id"]
    return cert


def complete_referral(R, status):
    R["status"] = status
    mint_certificate(R)
    for p in DB["placements"].values():
        if p["referral_id"] == R["id"] and p["status"] == "ACTIVE":
            p["status"] = "COMPLETED"
            touch(p)


def cancel_scheduled_sessions(placement):
    for ws in DB["work_sessions"].values():
        if ws["placement_id"] == placement["id"] and ws["attendance_status"] == "SCHEDULED":
            ws["attendance_status"] = "CANCELLED"
            touch(ws)


# =============================================================================
# Logical clock endpoint
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    global CLOCK_RAW, CLOCK_DT
    _, role = auth()
    require_role(role, {"CourtClerk", "ProgramCoordinator"})
    b = body()
    raw = b.get("to_iso8601")
    if not isinstance(raw, str):
        v_err("to_iso8601 must be an ISO-8601 datetime string")
    try:
        dt = _parse(raw)
    except Exception:
        v_err("to_iso8601 is not a valid ISO-8601 datetime")
    CLOCK_RAW = raw
    CLOCK_DT = dt
    return ok({"current_utc": CLOCK_RAW}, status=200)


# =============================================================================
# Participant
# =============================================================================
@app.route("/participants", methods=["POST"])
def participant_create():
    _, role = auth()
    require_role(role, {"CourtClerk", "ProgramCoordinator"})
    b = body()
    full_name = req_str(b, "full_name")
    dob = req_datetime(b, "date_of_birth")
    email = req_str(b, "contact_email")
    risk = opt_enum(b, "risk_level", "risk_level", "LOW")
    rec = create("participants", {
        "full_name": full_name,
        "date_of_birth": dob,
        "contact_email": email,
        "risk_level": risk,
    })
    return ok(_serialize(rec), status=201)


@app.route("/participants/<rid>", methods=["GET"])
def participant_get(rid):
    _, role = auth()
    require_role(role, ROLES)
    return ok(_serialize(get_or_404("participants", rid)))


@app.route("/participants", methods=["GET"])
def participant_list():
    _, role = auth()
    require_role(role, ROLES)
    items = list(DB["participants"].values())
    risk = request.args.get("risk_level")
    if risk is not None:
        items = [x for x in items if x["risk_level"] == risk]
    return list_response(items)


# =============================================================================
# Site
# =============================================================================
@app.route("/sites", methods=["POST"])
def site_create():
    _, role = auth()
    require_role(role, {"ProgramCoordinator"})
    b = body()
    name = req_str(b, "name")
    agency = req_enum(b, "agency_type", "agency_type")
    address = req_str(b, "address")
    capacity = req_int(b, "capacity_slots", minimum=1)
    rec = create("sites", {
        "name": name,
        "agency_type": agency,
        "address": address,
        "capacity_slots": capacity,
        "status": "PROSPECTIVE",
    })
    return ok(_serialize(rec), status=201)


@app.route("/sites/<rid>", methods=["GET"])
def site_get(rid):
    _, role = auth()
    require_role(role, ROLES)
    return ok(_serialize(get_or_404("sites", rid)))


@app.route("/sites", methods=["GET"])
def site_list():
    _, role = auth()
    require_role(role, ROLES)
    items = list(DB["sites"].values())
    status = request.args.get("status")
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return list_response(items)


@app.route("/sites/<rid>/activate", methods=["POST"])
def site_activate(rid):
    _, role = auth()
    require_role(role, {"ProgramCoordinator"})
    site = get_or_404("sites", rid)
    if site["status"] not in ("PROSPECTIVE", "PAUSED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Site cannot be activated from its current state")
    if not has_valid_insurance(site):
        raise ApiError("ERR_INSURANCE_INVALID", 409, "Site lacks a VERIFIED, non-expired insurance policy")
    site["status"] = "ACCEPTING"
    touch(site)
    return ok(_serialize(site))


@app.route("/sites/<rid>/pause", methods=["POST"])
def site_pause(rid):
    _, role = auth()
    require_role(role, {"ProgramCoordinator"})
    site = get_or_404("sites", rid)
    if site["status"] != "ACCEPTING":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an ACCEPTING site can be paused")
    site["status"] = "PAUSED"
    touch(site)
    return ok(_serialize(site))


# =============================================================================
# InsurancePolicy
# =============================================================================
@app.route("/insurance-policies", methods=["POST"])
def policy_create():
    _, role = auth()
    require_role(role, {"ProgramCoordinator"})
    b = body()
    site_id = req_str(b, "site_id")
    get_or_404("sites", site_id)
    carrier = req_str(b, "carrier")
    coverage = req_int(b, "coverage_amount_cents", minimum=0)
    eff = req_datetime(b, "effective_date")
    exp = req_datetime(b, "expiry_date")
    rec = create("insurance_policies", {
        "site_id": site_id,
        "carrier": carrier,
        "coverage_amount_cents": coverage,
        "effective_date": eff,
        "expiry_date": exp,
        "status": "PENDING",
    })
    return ok(_serialize(rec), status=201)


@app.route("/insurance-policies/<rid>", methods=["GET"])
def policy_get(rid):
    _, role = auth()
    require_role(role, ROLES)
    return ok(_serialize(get_or_404("insurance_policies", rid)))


@app.route("/insurance-policies", methods=["GET"])
def policy_list():
    _, role = auth()
    require_role(role, ROLES)
    items = list(DB["insurance_policies"].values())
    site_id = request.args.get("site_id")
    status = request.args.get("status")
    if site_id is not None:
        items = [x for x in items if x["site_id"] == site_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return list_response(items)


@app.route("/insurance-policies/<rid>/verify", methods=["POST"])
def policy_verify(rid):
    _, role = auth()
    require_role(role, {"ProgramCoordinator"})
    p = get_or_404("insurance_policies", rid)
    if p["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a PENDING policy can be verified")
    if _parse(p["expiry_date"]) <= CLOCK_DT:
        raise ApiError("ERR_INSURANCE_INVALID", 409, "Policy has already expired")
    p["status"] = "VERIFIED"
    touch(p)
    return ok(_serialize(p))


@app.route("/insurance-policies/<rid>/reject", methods=["POST"])
def policy_reject(rid):
    _, role = auth()
    require_role(role, {"ProgramCoordinator"})
    p = get_or_404("insurance_policies", rid)
    if p["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a PENDING policy can be rejected")
    p["status"] = "REJECTED"
    touch(p)
    return ok(_serialize(p))


# =============================================================================
# Supervisor
# =============================================================================
@app.route("/supervisors", methods=["POST"])
def supervisor_create():
    _, role = auth()
    require_role(role, {"ProgramCoordinator"})
    b = body()
    site_id = req_str(b, "site_id")
    get_or_404("sites", site_id)
    full_name = req_str(b, "full_name")
    if "max_concurrent_participants" in b and b["max_concurrent_participants"] is not None:
        mcp = req_int(b, "max_concurrent_participants", minimum=1)
    else:
        mcp = 5
    rec = create("supervisors", {
        "site_id": site_id,
        "full_name": full_name,
        "max_concurrent_participants": mcp,
    })
    return ok(_serialize(rec), status=201)


@app.route("/supervisors/<rid>", methods=["GET"])
def supervisor_get(rid):
    _, role = auth()
    require_role(role, ROLES)
    return ok(_serialize(get_or_404("supervisors", rid)))


@app.route("/supervisors", methods=["GET"])
def supervisor_list():
    _, role = auth()
    require_role(role, ROLES)
    items = list(DB["supervisors"].values())
    site_id = request.args.get("site_id")
    if site_id is not None:
        items = [x for x in items if x["site_id"] == site_id]
    return list_response(items)


# =============================================================================
# Referral
# =============================================================================
@app.route("/referrals", methods=["POST"])
def referral_create():
    _, role = auth()
    require_role(role, {"CourtClerk"})
    b = body()
    participant_id = req_str(b, "participant_id")
    get_or_404("participants", participant_id)
    court_case = req_str(b, "court_case_number")
    offense = req_enum(b, "offense_class", "offense_class")
    hours_ordered = req_hours(b, "hours_ordered")
    deadline = req_datetime(b, "deadline_date")
    indigency = opt_enum(b, "indigency_status", "indigency_status", "NONE")
    rec = create("referrals", {
        "participant_id": participant_id,
        "court_case_number": court_case,
        "offense_class": offense,
        "hours_ordered": hours_ordered,
        "deadline_date": deadline,
        "indigency_status": indigency,
        "hours_completed": 0.0,
        "hours_converted": 0.0,
        "hours_outstanding": hours_ordered,
        "fees_settled_cents": 0,
        "certificate_id": None,
        "status": "ACTIVE",
    })
    return ok(_serialize(rec), status=201)


@app.route("/referrals/<rid>", methods=["GET"])
def referral_get(rid):
    _, role = auth()
    require_role(role, ROLES)
    return ok(_serialize(get_or_404("referrals", rid)))


@app.route("/referrals", methods=["GET"])
def referral_list():
    _, role = auth()
    require_role(role, ROLES)
    items = list(DB["referrals"].values())
    participant_id = request.args.get("participant_id")
    status = request.args.get("status")
    if participant_id is not None:
        items = [x for x in items if x["participant_id"] == participant_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return list_response(items)


@app.route("/referrals/<rid>/summary", methods=["GET"])
def referral_summary(rid):
    _, role = auth()
    require_role(role, ROLES)
    R = get_or_404("referrals", rid)
    data = {
        "referral_id": R["id"],
        "hours_ordered": R["hours_ordered"],
        "hours_completed": R["hours_completed"],
        "hours_converted": R["hours_converted"],
        "hours_outstanding": R["hours_outstanding"],
        "fees_settled_cents": R["fees_settled_cents"],
        "status": R["status"],
        "certificate_id": R["certificate_id"],
    }
    return ok(data)


@app.route("/referrals/<rid>/reinstate", methods=["POST"])
def referral_reinstate(rid):
    _, role = auth()
    require_role(role, {"CourtClerk"})
    R = get_or_404("referrals", rid)
    if R["status"] != "NON_COMPLIANT":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a NON_COMPLIANT referral can be reinstated")
    R["status"] = "ACTIVE"
    touch(R)
    for p in DB["placements"].values():
        if p["referral_id"] == R["id"] and p["status"] == "SUSPENDED":
            p["status"] = "ACTIVE"
            touch(p)
    return ok(_serialize(R))


@app.route("/referrals/<rid>/terminate", methods=["POST"])
def referral_terminate(rid):
    _, role = auth()
    require_role(role, {"CourtClerk"})
    R = get_or_404("referrals", rid)
    if R["status"] != "NON_COMPLIANT":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a NON_COMPLIANT referral can be terminated")
    R["status"] = "TERMINATED"
    touch(R)
    for p in DB["placements"].values():
        if p["referral_id"] == R["id"] and p["status"] in ("PROPOSED", "ACTIVE", "SUSPENDED"):
            was_active = p["status"] == "ACTIVE"
            p["status"] = "TERMINATED"
            touch(p)
            if was_active:
                cancel_scheduled_sessions(p)
    return ok(_serialize(R))


# =============================================================================
# Placement
# =============================================================================
@app.route("/placements", methods=["POST"])
def placement_create():
    _, role = auth()
    require_role(role, {"ProgramCoordinator"})
    b = body()
    referral_id = req_str(b, "referral_id")
    get_or_404("referrals", referral_id)
    site_id = req_str(b, "site_id")
    get_or_404("sites", site_id)
    supervisor_id = req_str(b, "supervisor_id")
    supervisor = get_or_404("supervisors", supervisor_id)
    if supervisor["site_id"] != site_id:
        raise ApiError("ERR_SUPERVISOR_SITE_MISMATCH", 422,
                       "Supervisor does not belong to the placement's site")
    rec = create("placements", {
        "referral_id": referral_id,
        "site_id": site_id,
        "supervisor_id": supervisor_id,
        "waiver_signed": False,
        "waiver_signed_at": None,
        "waiver_signature_name": None,
        "status": "PROPOSED",
    })
    return ok(_serialize(rec), status=201)


@app.route("/placements/<rid>", methods=["GET"])
def placement_get(rid):
    _, role = auth()
    require_role(role, ROLES)
    return ok(_serialize(get_or_404("placements", rid)))


@app.route("/placements", methods=["GET"])
def placement_list():
    _, role = auth()
    require_role(role, ROLES)
    items = list(DB["placements"].values())
    for f in ("referral_id", "site_id", "supervisor_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [x for x in items if x[f] == val]
    return list_response(items)


@app.route("/placements/<rid>/sign-waiver", methods=["POST"])
def placement_sign_waiver(rid):
    uid, role = auth()
    require_role(role, {"Participant"})
    placement = get_or_404("placements", rid)
    referral = DB["referrals"].get(placement["referral_id"])
    if referral is None or referral["participant_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Participant does not own this placement's referral")
    b = body()
    signature = req_str(b, "signature_name")
    if placement["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Waiver can only be signed on a PROPOSED placement")
    placement["waiver_signed"] = True
    placement["waiver_signed_at"] = CLOCK_RAW
    placement["waiver_signature_name"] = signature
    touch(placement)
    return ok(_serialize(placement))


@app.route("/placements/<rid>/activate", methods=["POST"])
def placement_activate(rid):
    _, role = auth()
    require_role(role, {"ProgramCoordinator"})
    placement = get_or_404("placements", rid)
    if placement["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a PROPOSED placement can be activated")
    referral = DB["referrals"].get(placement["referral_id"])
    site = DB["sites"].get(placement["site_id"])
    if referral is None or referral["status"] != "ACTIVE":
        raise ApiError("ERR_REFERRAL_NOT_ACTIVE", 409, "Referral must be ACTIVE")
    if not placement["waiver_signed"]:
        raise ApiError("ERR_WAIVER_REQUIRED", 409, "Waiver must be signed before activation")
    if site is None or site["status"] != "ACCEPTING":
        raise ApiError("ERR_SITE_NOT_ACCEPTING", 409, "Site must be ACCEPTING")
    if not has_valid_insurance(site):
        raise ApiError("ERR_INSURANCE_INVALID", 409, "Site lacks a VERIFIED, non-expired insurance policy")
    placement["status"] = "ACTIVE"
    touch(placement)
    return ok(_serialize(placement))


@app.route("/placements/<rid>/terminate", methods=["POST"])
def placement_terminate(rid):
    _, role = auth()
    require_role(role, {"ProgramCoordinator"})
    placement = get_or_404("placements", rid)
    if placement["status"] not in ("PROPOSED", "ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Placement cannot be terminated from its current state")
    was_active = placement["status"] == "ACTIVE"
    placement["status"] = "TERMINATED"
    touch(placement)
    if was_active:
        cancel_scheduled_sessions(placement)
    return ok(_serialize(placement))


# =============================================================================
# WorkSession
# =============================================================================
def _interval(rec):
    return _parse(rec["scheduled_start"]), _parse(rec["scheduled_end"])


def _overlaps(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


@app.route("/work-sessions", methods=["POST"])
def session_create():
    _, role = auth()
    require_role(role, {"SiteSupervisor", "ProgramCoordinator"})
    b = body()
    placement_id = req_str(b, "placement_id")
    placement = get_or_404("placements", placement_id)
    category = opt_enum(b, "session_category", "session_category", "STANDARD")
    start = req_datetime(b, "scheduled_start")
    end = req_datetime(b, "scheduled_end")
    s_dt = _parse(start)
    e_dt = _parse(end)
    if not (e_dt > s_dt):
        v_err("scheduled_end must be strictly after scheduled_start")

    referral = DB["referrals"].get(placement["referral_id"])
    participant_id = referral["participant_id"]
    site_id = placement["site_id"]
    supervisor_id = placement["supervisor_id"]

    # (priority 14) Participant rest buffer
    for ws in DB["work_sessions"].values():
        if ws.get("_referral_id") is None:
            continue
        if ws["participant_id"] != participant_id:
            continue
        if ws["attendance_status"] not in ("SCHEDULED", "CHECKED_IN", "COMPLETED"):
            continue
        os_, oe_ = _interval(ws)
        if _overlaps(s_dt, e_dt, os_, oe_):
            gap = 0.0
        elif s_dt >= oe_:
            gap = (s_dt - oe_).total_seconds() / 60.0
        else:
            gap = (os_ - e_dt).total_seconds() / 60.0
        if gap < REST_BUFFER_MINUTES:
            raise ApiError("ERR_SESSION_OVERLAP", 409,
                           "Session is within the participant rest buffer of another session")

    # (priority 15) Supervisor double-booking
    for ws in DB["work_sessions"].values():
        if ws["attendance_status"] not in ("SCHEDULED", "CHECKED_IN"):
            continue
        other_pl = DB["placements"].get(ws["placement_id"])
        if other_pl is None or other_pl["supervisor_id"] != supervisor_id:
            continue
        os_, oe_ = _interval(ws)
        if _overlaps(s_dt, e_dt, os_, oe_):
            raise ApiError("ERR_SUPERVISOR_DOUBLE_BOOKED", 409,
                           "Assigned supervisor already staffs an overlapping session")

    # (priority 16) Site capacity
    site = DB["sites"].get(site_id)
    concurrent = 0
    for ws in DB["work_sessions"].values():
        if ws["site_id"] != site_id:
            continue
        if ws["attendance_status"] not in ("SCHEDULED", "CHECKED_IN"):
            continue
        os_, oe_ = _interval(ws)
        if _overlaps(s_dt, e_dt, os_, oe_):
            concurrent += 1
    if concurrent + 1 > site["capacity_slots"]:
        raise ApiError("ERR_SITE_CAPACITY_EXCEEDED", 409, "Site capacity exceeded for this interval")

    rec = create("work_sessions", {
        "placement_id": placement_id,
        "participant_id": participant_id,
        "site_id": site_id,
        "session_category": category,
        "scheduled_start": start,
        "scheduled_end": end,
        "check_in_at": None,
        "check_out_at": None,
        "claimed_hours": None,
        "verified_hours": None,
        "attendance_status": "SCHEDULED",
        "verification_status": "PENDING",
        "_referral_id": referral["id"],
    })
    return ok(_serialize(rec), status=201)


@app.route("/work-sessions/<rid>", methods=["GET"])
def session_get(rid):
    _, role = auth()
    require_role(role, ROLES)
    return ok(_serialize(get_or_404("work_sessions", rid)))


@app.route("/work-sessions", methods=["GET"])
def session_list():
    _, role = auth()
    require_role(role, ROLES)
    items = list(DB["work_sessions"].values())
    placement_id = request.args.get("placement_id")
    att = request.args.get("attendance_status")
    if placement_id is not None:
        items = [x for x in items if x["placement_id"] == placement_id]
    if att is not None:
        items = [x for x in items if x["attendance_status"] == att]
    return list_response(items)


def _session_supervisor_owner(uid, session):
    placement = DB["placements"].get(session["placement_id"])
    if placement is None or placement["supervisor_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Acting supervisor is not this placement's supervisor")
    return placement


@app.route("/work-sessions/<rid>/check-in", methods=["POST"])
def session_check_in(rid):
    uid, role = auth()
    require_role(role, {"SiteSupervisor"})
    session = get_or_404("work_sessions", rid)
    placement = _session_supervisor_owner(uid, session)
    b = body()
    check_in = opt_datetime(b, "check_in_at")
    if session["attendance_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Session must be SCHEDULED to check in")
    if placement["status"] != "ACTIVE":
        raise ApiError("ERR_PLACEMENT_NOT_ACTIVE", 409, "Placement must be ACTIVE for check-in")
    session["check_in_at"] = check_in if check_in is not None else CLOCK_RAW
    session["attendance_status"] = "CHECKED_IN"
    touch(session)
    return ok(_serialize(session))


@app.route("/work-sessions/<rid>/check-out", methods=["POST"])
def session_check_out(rid):
    uid, role = auth()
    require_role(role, {"SiteSupervisor"})
    session = get_or_404("work_sessions", rid)
    _session_supervisor_owner(uid, session)
    b = body()
    check_out = opt_datetime(b, "check_out_at")
    if session["attendance_status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", 409, "Session must be CHECKED_IN to check out")
    co = check_out if check_out is not None else CLOCK_RAW
    ci_dt = _parse(session["check_in_at"])
    co_dt = _parse(co)
    if not (co_dt > ci_dt):
        raise ApiError("ERR_CHECKOUT_BEFORE_CHECKIN", 422, "check_out_at must be strictly after check_in_at")
    session["check_out_at"] = co
    session["attendance_status"] = "COMPLETED"
    raw_hours = (co_dt - ci_dt).total_seconds() / 3600.0
    session["claimed_hours"] = round_quarter(raw_hours)
    touch(session)
    return ok(_serialize(session))


@app.route("/work-sessions/<rid>/verify", methods=["POST"])
def session_verify(rid):
    uid, role = auth()
    require_role(role, {"SiteSupervisor"})
    session = get_or_404("work_sessions", rid)
    _session_supervisor_owner(uid, session)
    b = body()
    outcome = req_enum(b, "outcome", "verify_outcome")
    attested = None
    if "attested_hours" in b and b["attested_hours"] is not None:
        attested = req_hours(b, "attested_hours")
    if session["attendance_status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", 409, "Session attendance must be COMPLETED to verify")
    R = DB["referrals"].get(session["_referral_id"])

    if outcome == "VERIFIED":
        if session["verification_status"] not in ("PENDING", "DISPUTED"):
            raise ApiError("ERR_INVALID_STATE", 409, "Verification not allowed from current status")
        if attested is not None:
            vh = round_quarter(attested)
        else:
            vh = session["claimed_hours"]
        if vh > session["claimed_hours"]:
            raise ApiError("ERR_VERIFIED_HOURS_EXCEED_CLAIMED", 422,
                           "attested_hours exceeds claimed_hours")
        session["verification_status"] = "VERIFIED"
        session["verified_hours"] = vh
        touch(session)
        recompute_ledger(R)
        if (R["status"] == "ACTIVE" and R["hours_outstanding"] == 0
                and R["hours_completed"] >= float(R["hours_ordered"])):
            complete_referral(R, "COMPLETED")
        touch(R)
    elif outcome == "DISPUTED":
        if session["verification_status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", 409, "DISPUTED allowed only from PENDING")
        session["verification_status"] = "DISPUTED"
        touch(session)
    else:  # REJECTED
        if session["verification_status"] not in ("PENDING", "DISPUTED"):
            raise ApiError("ERR_INVALID_STATE", 409, "REJECTED allowed only from PENDING or DISPUTED")
        session["verification_status"] = "REJECTED"
        touch(session)
    return ok(_serialize(session))


@app.route("/work-sessions/<rid>/void", methods=["POST"])
def session_void(rid):
    uid, role = auth()
    require_role(role, {"ProgramCoordinator", "SiteSupervisor"})
    session = get_or_404("work_sessions", rid)
    b = body()
    if session["attendance_status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a COMPLETED session can be voided")
    R = DB["referrals"].get(session["_referral_id"])
    was_verified = session["verification_status"] == "VERIFIED"
    if was_verified and R is not None and R["status"] in ("CONVERTED", "TERMINATED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Cannot void: referral is already terminal by another path")
    session["attendance_status"] = "VOIDED"
    touch(session)
    if was_verified and R is not None:
        recompute_ledger(R)
        if R["status"] == "COMPLETED" and R["hours_completed"] < float(R["hours_ordered"]):
            R["status"] = "ACTIVE"
            R["certificate_id"] = None
        touch(R)
    return ok(_serialize(session))


# =============================================================================
# FeeConversion
# =============================================================================
@app.route("/fee-conversions", methods=["POST"])
def fc_create():
    uid, role = auth()
    require_role(role, {"Participant", "ProgramCoordinator"})
    b = body()
    referral_id = req_str(b, "referral_id")
    R = get_or_404("referrals", referral_id)
    if role == "Participant" and R["participant_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Participant does not own this referral")
    hours = req_hours(b, "hours_to_convert")
    expected = b.get("expected_referral_version")
    if not is_int(expected):
        v_err("expected_referral_version must be an integer")
    if expected != R["version"]:
        raise ApiError("ERR_STALE_REFERRAL_VERSION", 412,
                       "expected_referral_version does not match the referral's current version")
    if hours > R["hours_outstanding"]:
        raise ApiError("ERR_HOURS_EXCEED_OUTSTANDING", 422,
                       "hours_to_convert exceeds referral.hours_outstanding")
    # supersede prior REQUESTED conversion for this referral
    for fc in DB["fee_conversions"].values():
        if fc["referral_id"] == referral_id and fc["status"] == "REQUESTED":
            fc["status"] = "DENIED"
            touch(fc)
    snapshot = R["indigency_status"]
    quoted = conversion_fee(hours, snapshot)
    rec = create("fee_conversions", {
        "referral_id": referral_id,
        "hours_to_convert": hours,
        "indigency_status_snapshot": snapshot,
        "quoted_fee_cents": quoted,
        "settlement_fee_cents": None,
        "settled_hours": None,
        "requested_by_user_id": uid,
        "approved_by_user_id": None,
        "status": "REQUESTED",
    })
    touch(R)  # advances referral version by 1
    return ok(_serialize(rec), status=201)


@app.route("/fee-conversions/<rid>", methods=["GET"])
def fc_get(rid):
    _, role = auth()
    require_role(role, ROLES)
    return ok(_serialize(get_or_404("fee_conversions", rid)))


@app.route("/fee-conversions", methods=["GET"])
def fc_list():
    _, role = auth()
    require_role(role, ROLES)
    items = list(DB["fee_conversions"].values())
    referral_id = request.args.get("referral_id")
    status = request.args.get("status")
    if referral_id is not None:
        items = [x for x in items if x["referral_id"] == referral_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return list_response(items)


@app.route("/fee-conversions/<rid>/approve", methods=["POST"])
def fc_approve(rid):
    uid, role = auth()
    require_role(role, {"ProgramCoordinator"})
    fc = get_or_404("fee_conversions", rid)
    if fc["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a REQUESTED conversion can be approved")
    R = DB["referrals"].get(fc["referral_id"])
    if R is None or R["status"] != "ACTIVE":
        raise ApiError("ERR_REFERRAL_NOT_ACTIVE", 409, "Referral must be ACTIVE")
    if uid == fc["requested_by_user_id"]:
        raise ApiError("ERR_SELF_APPROVAL", 403, "Approver must differ from requester (four-eyes)")
    fc["status"] = "APPROVED"
    fc["approved_by_user_id"] = uid
    touch(fc)
    return ok(_serialize(fc))


@app.route("/fee-conversions/<rid>/deny", methods=["POST"])
def fc_deny(rid):
    _, role = auth()
    require_role(role, {"ProgramCoordinator"})
    fc = get_or_404("fee_conversions", rid)
    if fc["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a REQUESTED conversion can be denied")
    fc["status"] = "DENIED"
    touch(fc)
    return ok(_serialize(fc))


@app.route("/fee-conversions/<rid>/pay", methods=["POST"])
def fc_pay(rid):
    uid, role = auth()
    require_role(role, {"Participant", "ProgramCoordinator"})
    fc = get_or_404("fee_conversions", rid)
    R = DB["referrals"].get(fc["referral_id"])
    if role == "Participant" and (R is None or R["participant_id"] != uid):
        raise ApiError("ERR_UNAUTHORIZED", 403, "Participant does not own this referral")
    b = body()
    amount = b.get("amount_cents")
    if not is_int(amount):
        v_err("amount_cents must be an integer")
    if fc["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an APPROVED conversion can be paid")
    if R["hours_outstanding"] <= 0:
        raise ApiError("ERR_NO_REMAINING_HOURS", 409, "Referral has no outstanding hours to settle")
    settled_hours = min(float(fc["hours_to_convert"]), float(R["hours_outstanding"]))
    settlement = conversion_fee(settled_hours, fc["indigency_status_snapshot"])
    if amount != settlement:
        v_err("amount_cents does not match the settlement fee")
    fc["settled_hours"] = settled_hours
    fc["settlement_fee_cents"] = settlement
    fc["status"] = "PAID"
    touch(fc)
    recompute_ledger(R)
    if (R["status"] == "ACTIVE" and R["hours_outstanding"] == 0
            and R["hours_completed"] < float(R["hours_ordered"])):
        complete_referral(R, "CONVERTED")
    touch(R)
    return ok(_serialize(fc))


@app.route("/fee-conversions/<rid>/reverse", methods=["POST"])
def fc_reverse(rid):
    _, role = auth()
    require_role(role, {"ProgramCoordinator"})
    fc = get_or_404("fee_conversions", rid)
    if fc["status"] not in ("APPROVED", "PAID"):
        raise ApiError("ERR_INVALID_STATE", 409, "Only an APPROVED or PAID conversion can be reversed")
    was_paid = fc["status"] == "PAID"
    fc["status"] = "REVERSED"
    touch(fc)
    if was_paid:
        R = DB["referrals"].get(fc["referral_id"])
        if R is not None:
            recompute_ledger(R)
            if R["status"] == "CONVERTED" and R["hours_outstanding"] > 0:
                R["status"] = "ACTIVE"
                R["certificate_id"] = None
            touch(R)
    return ok(_serialize(fc))


# =============================================================================
# ComplianceAction
# =============================================================================
@app.route("/compliance-actions", methods=["POST"])
def compliance_create():
    uid, role = auth()
    require_role(role, {"CourtClerk"})
    b = body()
    referral_id = req_str(b, "referral_id")
    R = get_or_404("referrals", referral_id)
    action_type = req_enum(b, "action_type", "action_type")
    reason = req_str(b, "reason")
    if action_type == "REPORT_BACK":
        if R["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "REPORT_BACK requires an ACTIVE referral")
        R["status"] = "NON_COMPLIANT"
        touch(R)
        for p in DB["placements"].values():
            if p["referral_id"] == R["id"] and p["status"] == "ACTIVE":
                p["status"] = "SUSPENDED"
                touch(p)
                cancel_scheduled_sessions(p)
    resulting = R["status"]
    rec = create("compliance_actions", {
        "referral_id": referral_id,
        "action_type": action_type,
        "reason": reason,
        "filed_by_user_id": uid,
        "resulting_referral_status": resulting,
    }, common=False)
    return ok(_serialize(rec), status=201)


@app.route("/compliance-actions/<rid>", methods=["GET"])
def compliance_get(rid):
    _, role = auth()
    require_role(role, ROLES)
    return ok(_serialize(get_or_404("compliance_actions", rid)))


@app.route("/compliance-actions", methods=["GET"])
def compliance_list():
    _, role = auth()
    require_role(role, ROLES)
    items = list(DB["compliance_actions"].values())
    referral_id = request.args.get("referral_id")
    if referral_id is not None:
        items = [x for x in items if x["referral_id"] == referral_id]
    return list_response(items)


# =============================================================================
# Certificate (read-only, auto-issued)
# =============================================================================
@app.route("/certificates/<rid>", methods=["GET"])
def certificate_get(rid):
    _, role = auth()
    require_role(role, ROLES)
    return ok(_serialize(get_or_404("certificates", rid)))


@app.route("/certificates", methods=["GET"])
def certificate_list():
    _, role = auth()
    require_role(role, ROLES)
    items = list(DB["certificates"].values())
    referral_id = request.args.get("referral_id")
    if referral_id is not None:
        items = [x for x in items if x["referral_id"] == referral_id]
    return list_response(items)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
