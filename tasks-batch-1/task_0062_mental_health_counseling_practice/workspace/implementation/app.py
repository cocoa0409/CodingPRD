import os
import re
import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"ClinicalDirector", "Therapist", "Biller", "FrontDesk"}

STD_RATE_CENTS = {"90791": 22000, "90834": 15000}
CPT_DURATION = {"90791": 60, "90834": 45}
CPT_CODES = {"90791", "90834"}

FPL_BASE = 15060
FPL_PER_ADDL = 5380

ASSOCIATE_TO_SUPERVISED_HOURS = 1500
INDEPENDENT_HOURS = 3000
SUPERVISION_RATIO = 20

W_IDEATION = Decimal("0.30")
W_PLAN = Decimal("0.30")
W_MEANS = Decimal("0.25")
W_PRIOR = Decimal("0.15")

APPT_NON_TERMINAL = {"SCHEDULED", "RENDERED", "COMPLETED", "CLAIMED"}

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.therapists = {}
        self.state_licenses = {}
        self.supervision_logs = {}
        self.patients = {}
        self.insurance_policies = {}
        self.payer_contracts = {}
        self.appointments = {}
        self.clinical_notes = {}
        self.claims = {}
        self.crisis_assessments = {}
        self.safety_plans = {}
        self.current_utc = None  # datetime, defaults to real now if unset


db = Store()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_CPT_DURATION_MISMATCH": 422,
    "ERR_PAYMENT_PATH_INVALID": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_SAFETY_PLAN_REQUIRED": 409,
    "ERR_PATIENT_ON_HOLD": 409,
    "ERR_NO_ACTIVE_LICENSE_IN_STATE": 409,
    "ERR_TELEHEALTH_NOT_AUTHORIZED": 409,
    "ERR_COSIGN_REQUIRED": 409,
    "ERR_PROMOTION_NOT_ELIGIBLE": 409,
    "ERR_THERAPIST_DOUBLE_BOOKED": 409,
    "ERR_PATIENT_DOUBLE_BOOKED": 409,
    "ERR_CLAIM_ALREADY_EXISTS": 409,
    "ERR_STALE_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_HTTP[error_id]
        self.message = message or error_id
        super().__init__(self.message)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def fmt_iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def server_now():
    if db.current_utc is not None:
        return db.current_utc
    return datetime.now(timezone.utc)


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns aware datetime in UTC. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def make_meta(extra=None):
    meta = {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, response_type="object", pagination=None):
    meta = make_meta(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def round2(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round_cents(decimal_value):
    return int(decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def new_base():
    ts = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def get_identity():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing X-User-Role or X-User-ID")
    return role, uid


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "Role not permitted for this endpoint")


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def get_body():
    if request.data:
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            body = None
    else:
        body = None
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be a non-empty string")
    return v


def require_int(body, field, min_v=None, max_v=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be an integer")
    if min_v is not None and v < min_v:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} below minimum")
    if max_v is not None and v > max_v:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} above maximum")
    return v


def require_number(body, field, min_v=None, max_v=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be a number")
    if min_v is not None and v < min_v:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} below minimum")
    if max_v is not None and v > max_v:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} above maximum")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be one of {sorted(allowed)}")
    return v


def require_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be a boolean")
    return v


def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit out of range")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items):
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


# ---------------------------------------------------------------------------
# License status evaluation (lazy expiry)
# ---------------------------------------------------------------------------
def license_effective_status(lic):
    if lic["status"] == "REVOKED":
        return "REVOKED"
    if lic["status"] == "ACTIVE":
        exp = parse_dt(lic["expires_on"])
        if server_now() >= exp:
            return "EXPIRED"
        return "ACTIVE"
    return lic["status"]


# ---------------------------------------------------------------------------
# Serialization (views)
# ---------------------------------------------------------------------------
def view_therapist(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "full_name": t["full_name"],
        "home_state_code": t["home_state_code"],
        "credential_status": t["credential_status"],
        "requires_supervision": t["requires_supervision"],
        "verified_direct_hours": t["verified_direct_hours"],
        "projected_direct_hours": t["projected_direct_hours"],
        "verified_supervision_hours": t["verified_supervision_hours"],
        "supervisor_id": t["supervisor_id"],
    }


def view_license(l):
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
        "therapist_id": l["therapist_id"],
        "state_code": l["state_code"],
        "license_number": l["license_number"],
        "status": license_effective_status(l),
        "expires_on": l["expires_on"],
        "telehealth_authorized": l["telehealth_authorized"],
    }


def view_suplog(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "therapist_id": s["therapist_id"],
        "supervisor_id": s["supervisor_id"],
        "hours": s["hours"],
        "logged_on": s["logged_on"],
        "status": s["status"],
    }


def view_patient(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "full_name": p["full_name"],
        "location_state_code": p["location_state_code"],
        "annual_household_income": p["annual_household_income"],
        "household_size": p["household_size"],
        "fpl_percent": p["fpl_percent"],
        "sliding_fee_multiplier": p["sliding_fee_multiplier"],
        "status": p["status"],
    }


def view_policy(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "patient_id": p["patient_id"],
        "contract_id": p["contract_id"],
        "cost_share_model": p["cost_share_model"],
        "copay_cents": p["copay_cents"],
        "coinsurance_rate": p["coinsurance_rate"],
        "deductible_total_cents": p["deductible_total_cents"],
        "deductible_met_cents": p["deductible_met_cents"],
    }


def view_contract(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "payer_name": c["payer_name"],
        "in_network": c["in_network"],
        "contracted_rate_90791_cents": c["contracted_rate_90791_cents"],
        "contracted_rate_90834_cents": c["contracted_rate_90834_cents"],
    }


def view_appointment(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "therapist_id": a["therapist_id"],
        "patient_id": a["patient_id"],
        "cpt_code": a["cpt_code"],
        "modality": a["modality"],
        "start_at": a["start_at"],
        "duration_minutes": a["duration_minutes"],
        "status": a["status"],
        "payment_path": a["payment_path"],
        "insurance_policy_id": a["insurance_policy_id"],
        "patient_charge_cents": a["patient_charge_cents"],
    }


def view_note(n):
    return {
        "id": n["id"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
        "appointment_id": n["appointment_id"],
        "narrative": n["narrative"],
        "status": n["status"],
        "signed_by_id": n["signed_by_id"],
        "cosigned_by_id": n["cosigned_by_id"],
    }


def view_claim(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "appointment_id": c["appointment_id"],
        "insurance_policy_id": c["insurance_policy_id"],
        "cpt_code": c["cpt_code"],
        "billed_charge_cents": c["billed_charge_cents"],
        "allowed_amount_cents": c["allowed_amount_cents"],
        "deductible_applied_cents": c["deductible_applied_cents"],
        "patient_responsibility_cents": c["patient_responsibility_cents"],
        "payer_paid_cents": c["payer_paid_cents"],
        "status": c["status"],
    }


def view_crisis(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "patient_id": c["patient_id"],
        "therapist_id": c["therapist_id"],
        "ideation_score": c["ideation_score"],
        "plan_score": c["plan_score"],
        "means_access_score": c["means_access_score"],
        "prior_attempts_score": c["prior_attempts_score"],
        "risk_score": c["risk_score"],
        "risk_band": c["risk_band"],
        "status": c["status"],
    }


def view_safety(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "crisis_assessment_id": s["crisis_assessment_id"],
        "warning_signs": s["warning_signs"],
        "coping_strategies": s["coping_strategies"],
        "emergency_contacts": s["emergency_contacts"],
    }


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def compute_sliding_fee(income, household_size):
    fpl = FPL_BASE + FPL_PER_ADDL * (household_size - 1)
    fpl_percent = round2(Decimal(str(income)) / Decimal(str(fpl)) * 100)
    if fpl_percent <= 150:
        mult = 0.20
    elif fpl_percent <= 200:
        mult = 0.40
    elif fpl_percent <= 250:
        mult = 0.60
    elif fpl_percent <= 300:
        mult = 0.80
    else:
        mult = 1.00
    return fpl_percent, mult


def compute_self_pay_charge(cpt_code, multiplier):
    std = STD_RATE_CENTS[cpt_code]
    return round_cents(Decimal(str(std)) * Decimal(str(multiplier)))


def compute_crisis_risk(ideation, plan, means, prior):
    raw = (W_IDEATION * ideation + W_PLAN * plan +
           W_MEANS * means + W_PRIOR * prior)
    score = float((raw / Decimal("3.0") * Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP))
    if score >= 70:
        band = "HIGH"
    elif score >= 40:
        band = "MODERATE"
    else:
        band = "LOW"
    return score, band


def recompute_verified_direct_hours(therapist_id):
    total = 0
    for a in db.appointments.values():
        if a["therapist_id"] != therapist_id:
            continue
        if a["status"] != "COMPLETED":
            continue
        note = note_for_appointment(a["id"])
        if note and note["status"] == "CO_SIGNED":
            total += a["duration_minutes"]
    return round2(Decimal(total) / Decimal("60"))


def recompute_projected_direct_hours(therapist_id):
    total = 0
    for a in db.appointments.values():
        if a["therapist_id"] != therapist_id:
            continue
        if a["status"] in {"SCHEDULED", "RENDERED", "COMPLETED"}:
            total += a["duration_minutes"]
    return round2(Decimal(total) / Decimal("60"))


def recompute_verified_supervision_hours(therapist_id):
    total = Decimal("0")
    for s in db.supervision_logs.values():
        if s["therapist_id"] == therapist_id and s["status"] == "ACCEPTED":
            total += Decimal(str(s["hours"]))
    return round2(total)


def note_for_appointment(appointment_id):
    for n in db.clinical_notes.values():
        if n["appointment_id"] == appointment_id:
            return n
    return None


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_or_404(coll, _id):
    rec = coll.get(_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Resource not found")
    return rec


# ===========================================================================
# THERAPIST
# ===========================================================================
@app.route("/therapists", methods=["POST"])
def create_therapist():
    role, uid = get_identity()
    require_roles(role, {"ClinicalDirector"})
    body = get_body()
    full_name = require_str(body, "full_name")

    home_state = body.get("home_state_code")
    if home_state is not None:
        if not isinstance(home_state, str):
            raise ApiError("ERR_INVALID_REQUEST", "home_state_code must be a string")
        home_state = home_state.upper()

    supervisor_id = body.get("supervisor_id")
    if supervisor_id is not None:
        sup = db.therapists.get(supervisor_id)
        if sup is None:
            raise ApiError("ERR_NOT_FOUND", "supervisor not found")
        if sup["credential_status"] != "INDEPENDENT":
            raise ApiError("ERR_INVALID_REQUEST", "supervisor must be INDEPENDENT")

    t = new_base()
    t.update({
        "full_name": full_name,
        "home_state_code": home_state,
        "credential_status": "ASSOCIATE",
        "requires_supervision": True,
        "verified_direct_hours": 0,
        "projected_direct_hours": 0,
        "verified_supervision_hours": 0,
        "supervisor_id": supervisor_id,
    })
    db.therapists[t["id"]] = t
    return success(view_therapist(t), 201)


@app.route("/therapists/<tid>", methods=["GET"])
def get_therapist(tid):
    role, uid = get_identity()
    require_roles(role, ROLES)
    t = get_or_404(db.therapists, tid)
    return success(view_therapist(t), 200)


@app.route("/therapists", methods=["GET"])
def list_therapists():
    role, uid = get_identity()
    require_roles(role, ROLES)
    items = list(db.therapists.values())
    sup = request.args.get("supervisor_id")
    if sup is not None:
        items = [t for t in items if t["supervisor_id"] == sup]
    page, pg = paginate(items)
    return success([view_therapist(t) for t in page], 200, "array", pg)


@app.route("/therapists/<tid>/promote", methods=["POST"])
def promote_therapist(tid):
    role, uid = get_identity()
    require_roles(role, {"ClinicalDirector"})
    t = get_or_404(db.therapists, tid)
    body = get_body()
    require_fields(body, ["expected_therapist_version"])
    exp_v = require_int(body, "expected_therapist_version")

    cur = t["credential_status"]
    if cur not in {"ASSOCIATE", "SUPERVISED_PRACTICE"}:
        raise ApiError("ERR_INVALID_STATE", "promote not defined from this state")

    # state precondition (state) before promotion eligibility, then OCC last
    if cur == "ASSOCIATE":
        if t["verified_direct_hours"] < ASSOCIATE_TO_SUPERVISED_HOURS:
            raise ApiError("ERR_PROMOTION_NOT_ELIGIBLE", "insufficient verified direct hours")
        if exp_v != t["version"]:
            raise ApiError("ERR_STALE_VERSION", "version mismatch")
        t["credential_status"] = "SUPERVISED_PRACTICE"
        t["requires_supervision"] = True
    else:  # SUPERVISED_PRACTICE
        eligible = True
        if t["verified_direct_hours"] < INDEPENDENT_HOURS:
            eligible = False
        if t["verified_supervision_hours"] < (t["verified_direct_hours"] / SUPERVISION_RATIO):
            eligible = False
        has_active_license = any(
            l["therapist_id"] == tid and license_effective_status(l) == "ACTIVE"
            for l in db.state_licenses.values()
        )
        if not has_active_license:
            eligible = False
        if not eligible:
            raise ApiError("ERR_PROMOTION_NOT_ELIGIBLE", "promotion thresholds not met")
        if exp_v != t["version"]:
            raise ApiError("ERR_STALE_VERSION", "version mismatch")
        t["credential_status"] = "INDEPENDENT"
        t["requires_supervision"] = False
    touch(t)
    return success(view_therapist(t), 200)


@app.route("/therapists/<tid>/suspend", methods=["POST"])
def suspend_therapist(tid):
    role, uid = get_identity()
    require_roles(role, {"ClinicalDirector"})
    t = get_or_404(db.therapists, tid)
    body = get_body()
    require_fields(body, ["expected_therapist_version"])
    exp_v = require_int(body, "expected_therapist_version")

    if t["credential_status"] not in {"ASSOCIATE", "SUPERVISED_PRACTICE", "INDEPENDENT"}:
        raise ApiError("ERR_INVALID_STATE", "suspend not defined from this state")
    if exp_v != t["version"]:
        raise ApiError("ERR_STALE_VERSION", "version mismatch")

    t["credential_status"] = "SUSPENDED"
    # cascade: cancel SCHEDULED appointments
    for a in db.appointments.values():
        if a["therapist_id"] == tid and a["status"] == "SCHEDULED":
            a["status"] = "CANCELLED"
            touch(a)
    touch(t)
    return success(view_therapist(t), 200)


# ===========================================================================
# STATE LICENSE
# ===========================================================================
@app.route("/state-licenses", methods=["POST"])
def create_license():
    role, uid = get_identity()
    require_roles(role, {"ClinicalDirector"})
    body = get_body()
    require_fields(body, ["therapist_id", "state_code", "license_number", "expires_on"])
    therapist_id = require_str(body, "therapist_id")
    state_code = require_str(body, "state_code")
    license_number = require_str(body, "license_number")
    expires_on_raw = body["expires_on"]
    try:
        expires_on = fmt_iso(parse_dt(expires_on_raw))
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "expires_on must be ISO 8601")
    telehealth = body.get("telehealth_authorized", True)
    if not isinstance(telehealth, bool):
        raise ApiError("ERR_INVALID_REQUEST", "telehealth_authorized must be a boolean")

    # existence of FK
    get_or_404(db.therapists, therapist_id)

    l = new_base()
    l.update({
        "therapist_id": therapist_id,
        "state_code": state_code.upper(),
        "license_number": license_number,
        "status": "ACTIVE",
        "expires_on": expires_on,
        "telehealth_authorized": telehealth,
    })
    db.state_licenses[l["id"]] = l
    return success(view_license(l), 201)


@app.route("/state-licenses/<lid>", methods=["GET"])
def get_license(lid):
    role, uid = get_identity()
    require_roles(role, ROLES)
    l = get_or_404(db.state_licenses, lid)
    return success(view_license(l), 200)


@app.route("/state-licenses", methods=["GET"])
def list_licenses():
    role, uid = get_identity()
    require_roles(role, ROLES)
    items = list(db.state_licenses.values())
    tid = request.args.get("therapist_id")
    sc = request.args.get("state_code")
    if tid is not None:
        items = [l for l in items if l["therapist_id"] == tid]
    if sc is not None:
        items = [l for l in items if l["state_code"] == sc.upper()]
    page, pg = paginate(items)
    return success([view_license(l) for l in page], 200, "array", pg)


@app.route("/state-licenses/<lid>/revoke", methods=["POST"])
def revoke_license(lid):
    role, uid = get_identity()
    require_roles(role, {"ClinicalDirector"})
    l = get_or_404(db.state_licenses, lid)
    # transition defined only from ACTIVE (stored status). Lazy expiry does not change stored.
    if l["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "revoke not defined from this state")
    l["status"] = "REVOKED"
    touch(l)
    return success(view_license(l), 200)


# ===========================================================================
# SUPERVISION LOG
# ===========================================================================
@app.route("/supervision-logs", methods=["POST"])
def create_suplog():
    role, uid = get_identity()
    require_roles(role, {"ClinicalDirector", "Therapist"})
    body = get_body()
    require_fields(body, ["therapist_id", "supervisor_id", "hours", "logged_on"])
    therapist_id = require_str(body, "therapist_id")
    supervisor_id = require_str(body, "supervisor_id")
    hours = require_number(body, "hours")
    if hours <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "hours must be > 0")
    try:
        logged_on = fmt_iso(parse_dt(body["logged_on"]))
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "logged_on must be ISO 8601")

    get_or_404(db.therapists, therapist_id)
    get_or_404(db.therapists, supervisor_id)

    s = new_base()
    s.update({
        "therapist_id": therapist_id,
        "supervisor_id": supervisor_id,
        "hours": hours,
        "logged_on": logged_on,
        "status": "SUBMITTED",
    })
    db.supervision_logs[s["id"]] = s
    return success(view_suplog(s), 201)


@app.route("/supervision-logs/<sid>", methods=["GET"])
def get_suplog(sid):
    role, uid = get_identity()
    require_roles(role, {"ClinicalDirector", "Therapist"})
    s = get_or_404(db.supervision_logs, sid)
    return success(view_suplog(s), 200)


@app.route("/supervision-logs", methods=["GET"])
def list_suplogs():
    role, uid = get_identity()
    require_roles(role, {"ClinicalDirector", "Therapist"})
    items = list(db.supervision_logs.values())
    tid = request.args.get("therapist_id")
    sup = request.args.get("supervisor_id")
    if tid is not None:
        items = [s for s in items if s["therapist_id"] == tid]
    if sup is not None:
        items = [s for s in items if s["supervisor_id"] == sup]
    page, pg = paginate(items)
    return success([view_suplog(s) for s in page], 200, "array", pg)


@app.route("/supervision-logs/<sid>/accept", methods=["POST"])
def accept_suplog(sid):
    role, uid = get_identity()
    require_roles(role, {"ClinicalDirector"})
    s = get_or_404(db.supervision_logs, sid)
    if s["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "accept not defined from this state")
    sup = db.therapists.get(s["supervisor_id"])
    if sup is None or sup["credential_status"] != "INDEPENDENT":
        # supervisor must be INDEPENDENT — treat as invalid state precondition
        raise ApiError("ERR_INVALID_STATE", "supervisor is not INDEPENDENT")
    s["status"] = "ACCEPTED"
    touch(s)
    # cascade: recompute supervisee verified_supervision_hours
    sv = db.therapists.get(s["therapist_id"])
    if sv is not None:
        sv["verified_supervision_hours"] = recompute_verified_supervision_hours(s["therapist_id"])
        touch(sv)
    return success(view_suplog(s), 200)


@app.route("/supervision-logs/<sid>/reject", methods=["POST"])
def reject_suplog(sid):
    role, uid = get_identity()
    require_roles(role, {"ClinicalDirector"})
    s = get_or_404(db.supervision_logs, sid)
    if s["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "reject not defined from this state")
    s["status"] = "REJECTED"
    touch(s)
    return success(view_suplog(s), 200)


# ===========================================================================
# PATIENT
# ===========================================================================
@app.route("/patients", methods=["POST"])
def create_patient():
    role, uid = get_identity()
    require_roles(role, {"FrontDesk", "ClinicalDirector"})
    body = get_body()
    require_fields(body, ["full_name", "location_state_code",
                          "annual_household_income", "household_size"])
    full_name = require_str(body, "full_name")
    loc = require_str(body, "location_state_code")
    income = require_number(body, "annual_household_income", min_v=0)
    household = require_int(body, "household_size", min_v=1)

    fpl_percent, mult = compute_sliding_fee(income, household)
    p = new_base()
    p.update({
        "full_name": full_name,
        "location_state_code": loc.upper(),
        "annual_household_income": income,
        "household_size": household,
        "fpl_percent": fpl_percent,
        "sliding_fee_multiplier": mult,
        "status": "ACTIVE",
    })
    db.patients[p["id"]] = p
    return success(view_patient(p), 201)


@app.route("/patients/<pid>", methods=["GET"])
def get_patient(pid):
    role, uid = get_identity()
    require_roles(role, {"FrontDesk", "ClinicalDirector", "Therapist", "Biller"})
    p = get_or_404(db.patients, pid)
    return success(view_patient(p), 200)


@app.route("/patients", methods=["GET"])
def list_patients():
    role, uid = get_identity()
    require_roles(role, {"FrontDesk", "ClinicalDirector", "Therapist", "Biller"})
    items = list(db.patients.values())
    st = request.args.get("status")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    page, pg = paginate(items)
    return success([view_patient(p) for p in page], 200, "array", pg)


@app.route("/patients/<pid>/financials", methods=["PATCH"])
def update_patient_financials(pid):
    role, uid = get_identity()
    require_roles(role, {"FrontDesk", "ClinicalDirector"})
    p = get_or_404(db.patients, pid)
    body = get_body()
    require_fields(body, ["annual_household_income", "household_size"])
    income = require_number(body, "annual_household_income", min_v=0)
    household = require_int(body, "household_size", min_v=1)
    fpl_percent, mult = compute_sliding_fee(income, household)
    p["annual_household_income"] = income
    p["household_size"] = household
    p["fpl_percent"] = fpl_percent
    p["sliding_fee_multiplier"] = mult
    touch(p)
    return success(view_patient(p), 200)


# ===========================================================================
# INSURANCE POLICY
# ===========================================================================
@app.route("/insurance-policies", methods=["POST"])
def create_policy():
    role, uid = get_identity()
    require_roles(role, {"FrontDesk", "ClinicalDirector", "Biller"})
    body = get_body()
    require_fields(body, ["patient_id", "contract_id", "cost_share_model"])
    patient_id = require_str(body, "patient_id")
    contract_id = require_str(body, "contract_id")
    cost_share_model = require_enum(body, "cost_share_model", {"COPAY", "COINSURANCE"})

    copay = body.get("copay_cents", 0)
    if isinstance(copay, bool) or not isinstance(copay, int):
        raise ApiError("ERR_INVALID_REQUEST", "copay_cents must be an integer")
    if copay < 0:
        raise ApiError("ERR_INVALID_REQUEST", "copay_cents must be >= 0")

    coins = body.get("coinsurance_rate", 0)
    if isinstance(coins, bool) or not isinstance(coins, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "coinsurance_rate must be a number")
    if coins < 0 or coins > 1:
        raise ApiError("ERR_INVALID_REQUEST", "coinsurance_rate must be in [0,1]")

    deductible = body.get("deductible_total_cents", 0)
    if isinstance(deductible, bool) or not isinstance(deductible, int):
        raise ApiError("ERR_INVALID_REQUEST", "deductible_total_cents must be an integer")
    if deductible < 0:
        raise ApiError("ERR_INVALID_REQUEST", "deductible_total_cents must be >= 0")

    # existence of FKs left-to-right: patient then contract
    get_or_404(db.patients, patient_id)
    get_or_404(db.payer_contracts, contract_id)

    pol = new_base()
    pol.update({
        "patient_id": patient_id,
        "contract_id": contract_id,
        "cost_share_model": cost_share_model,
        "copay_cents": copay,
        "coinsurance_rate": coins,
        "deductible_total_cents": deductible,
        "deductible_met_cents": 0,
    })
    db.insurance_policies[pol["id"]] = pol
    return success(view_policy(pol), 201)


@app.route("/insurance-policies/<pid>", methods=["GET"])
def get_policy(pid):
    role, uid = get_identity()
    require_roles(role, {"FrontDesk", "ClinicalDirector", "Biller"})
    pol = get_or_404(db.insurance_policies, pid)
    return success(view_policy(pol), 200)


@app.route("/insurance-policies", methods=["GET"])
def list_policies():
    role, uid = get_identity()
    require_roles(role, {"FrontDesk", "ClinicalDirector", "Biller"})
    items = list(db.insurance_policies.values())
    pid = request.args.get("patient_id")
    cid = request.args.get("contract_id")
    if pid is not None:
        items = [p for p in items if p["patient_id"] == pid]
    if cid is not None:
        items = [p for p in items if p["contract_id"] == cid]
    page, pg = paginate(items)
    return success([view_policy(p) for p in page], 200, "array", pg)


# ===========================================================================
# PAYER CONTRACT
# ===========================================================================
@app.route("/payer-contracts", methods=["POST"])
def create_contract():
    role, uid = get_identity()
    require_roles(role, {"ClinicalDirector", "Biller"})
    body = get_body()
    require_fields(body, ["payer_name", "in_network",
                          "contracted_rate_90791_cents", "contracted_rate_90834_cents"])
    payer_name = require_str(body, "payer_name")
    in_network = require_bool(body, "in_network")
    r91 = require_int(body, "contracted_rate_90791_cents", min_v=0)
    r34 = require_int(body, "contracted_rate_90834_cents", min_v=0)

    c = new_base()
    c.update({
        "payer_name": payer_name,
        "in_network": in_network,
        "contracted_rate_90791_cents": r91,
        "contracted_rate_90834_cents": r34,
    })
    db.payer_contracts[c["id"]] = c
    return success(view_contract(c), 201)


@app.route("/payer-contracts/<cid>", methods=["GET"])
def get_contract(cid):
    role, uid = get_identity()
    require_roles(role, {"ClinicalDirector", "Biller", "FrontDesk"})
    c = get_or_404(db.payer_contracts, cid)
    return success(view_contract(c), 200)


# ===========================================================================
# APPOINTMENT
# ===========================================================================
def intervals_overlap_halfopen(s1, e1, s2, e2):
    # half-open [s,e): overlap iff s1 < e2 and s2 < e1
    return s1 < e2 and s2 < e1


def intervals_overlap_closed(s1, e1, s2, e2):
    # closed [s,e]: overlap/touch iff s1 <= e2 and s2 <= e1
    return s1 <= e2 and s2 <= e1


@app.route("/appointments", methods=["POST"])
def create_appointment():
    role, uid = get_identity()
    require_roles(role, {"FrontDesk", "Therapist", "ClinicalDirector"})
    body = get_body()
    require_fields(body, ["therapist_id", "patient_id", "cpt_code", "modality",
                          "start_at", "duration_minutes", "payment_path"])
    therapist_id = require_str(body, "therapist_id")
    patient_id = require_str(body, "patient_id")
    cpt_code = require_enum(body, "cpt_code", CPT_CODES)
    modality = require_enum(body, "modality", {"IN_PERSON", "TELEHEALTH"})
    try:
        start_at = parse_dt(body["start_at"])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "start_at must be ISO 8601")
    duration = require_int(body, "duration_minutes", min_v=1)
    payment_path = require_enum(body, "payment_path", {"INSURANCE", "SELF_PAY"})
    insurance_policy_id = body.get("insurance_policy_id")

    # existence: FK references left-to-right (therapist, patient)
    get_or_404(db.therapists, therapist_id)
    patient = get_or_404(db.patients, patient_id)

    # CPT/duration (priority 6)
    if duration != CPT_DURATION[cpt_code]:
        raise ApiError("ERR_CPT_DURATION_MISMATCH", "duration does not match CPT code")

    # payment-path coherence (priority 7)
    if payment_path == "INSURANCE":
        if insurance_policy_id is None:
            raise ApiError("ERR_PAYMENT_PATH_INVALID", "INSURANCE requires insurance_policy_id")
        pol = db.insurance_policies.get(insurance_policy_id)
        if pol is None:
            # FK existence handled within payment-path coherence semantics; spec says
            # policy whose patient_id == appt patient. A missing policy is a not-found FK.
            raise ApiError("ERR_NOT_FOUND", "insurance policy not found")
        if pol["patient_id"] != patient_id:
            raise ApiError("ERR_PAYMENT_PATH_INVALID", "policy does not belong to patient")
    else:  # SELF_PAY
        if insurance_policy_id is not None:
            raise ApiError("ERR_PAYMENT_PATH_INVALID", "SELF_PAY must not carry insurance_policy_id")

    end_at = start_at.timestamp() + duration * 60
    start_ts = start_at.timestamp()

    # therapist double-book (priority 15) — half-open
    for a in db.appointments.values():
        if a["therapist_id"] != therapist_id:
            continue
        if a["status"] not in APPT_NON_TERMINAL:
            continue
        a_start = parse_dt(a["start_at"]).timestamp()
        a_end = a_start + a["duration_minutes"] * 60
        if intervals_overlap_halfopen(start_ts, end_at, a_start, a_end):
            raise ApiError("ERR_THERAPIST_DOUBLE_BOOKED", "therapist double-booked")

    # patient double-book (priority 16) — closed
    for a in db.appointments.values():
        if a["patient_id"] != patient_id:
            continue
        if a["status"] not in APPT_NON_TERMINAL:
            continue
        a_start = parse_dt(a["start_at"]).timestamp()
        a_end = a_start + a["duration_minutes"] * 60
        if intervals_overlap_closed(start_ts, end_at, a_start, a_end):
            raise ApiError("ERR_PATIENT_DOUBLE_BOOKED", "patient double-booked")

    a = new_base()
    a.update({
        "therapist_id": therapist_id,
        "patient_id": patient_id,
        "cpt_code": cpt_code,
        "modality": modality,
        "start_at": fmt_iso(start_at),
        "duration_minutes": duration,
        "status": "SCHEDULED",
        "payment_path": payment_path,
        "insurance_policy_id": insurance_policy_id,
        "patient_charge_cents": 0,
    })
    db.appointments[a["id"]] = a
    return success(view_appointment(a), 201)


@app.route("/appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    role, uid = get_identity()
    require_roles(role, {"FrontDesk", "Therapist", "ClinicalDirector", "Biller"})
    a = get_or_404(db.appointments, aid)
    return success(view_appointment(a), 200)


@app.route("/appointments", methods=["GET"])
def list_appointments():
    role, uid = get_identity()
    require_roles(role, {"FrontDesk", "Therapist", "ClinicalDirector", "Biller"})
    items = list(db.appointments.values())
    for key in ("therapist_id", "patient_id", "insurance_policy_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a[key] == val]
    page, pg = paginate(items)
    return success([view_appointment(a) for a in page], 200, "array", pg)


@app.route("/appointments/<aid>/render", methods=["POST"])
def render_appointment(aid):
    role, uid = get_identity()
    require_roles(role, {"Therapist"})
    a = get_or_404(db.appointments, aid)
    # ownership (priority 3): X-User-ID must equal rendering therapist
    if uid != a["therapist_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "not the rendering therapist")

    if a["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "render not defined from this state")

    patient = db.patients[a["patient_id"]]
    therapist = db.therapists[a["therapist_id"]]

    # clinical-hold gate (priority 10) before licensure gates per validation table
    if patient["status"] == "ON_CLINICAL_HOLD":
        raise ApiError("ERR_PATIENT_ON_HOLD", "patient on clinical hold")

    # start_at <= now ; suspended check. These are state preconditions in the SM.
    # PRD §3.6 order: start_at, not suspended, then licensure, telehealth, hold.
    # Validation table priority places hold(10) before license(11)/telehealth(12).
    # We follow the priority table for error precedence among the gated errors.
    if parse_dt(a["start_at"]) > server_now():
        raise ApiError("ERR_INVALID_STATE", "session start_at is in the future")
    if therapist["credential_status"] == "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "therapist is suspended")

    # licensure gate (priority 11)
    matching = None
    for l in db.state_licenses.values():
        if l["therapist_id"] == a["therapist_id"] and \
           l["state_code"] == patient["location_state_code"] and \
           license_effective_status(l) == "ACTIVE":
            matching = l
            break
    if matching is None:
        raise ApiError("ERR_NO_ACTIVE_LICENSE_IN_STATE", "no active license in patient state")

    # telehealth gate (priority 12)
    if a["modality"] == "TELEHEALTH" and not matching["telehealth_authorized"]:
        raise ApiError("ERR_TELEHEALTH_NOT_AUTHORIZED", "telehealth not authorized")

    a["status"] = "RENDERED"
    if a["payment_path"] == "SELF_PAY":
        a["patient_charge_cents"] = compute_self_pay_charge(a["cpt_code"], patient["sliding_fee_multiplier"])
    touch(a)
    # cascade: recompute projected_direct_hours
    therapist["projected_direct_hours"] = recompute_projected_direct_hours(a["therapist_id"])
    touch(therapist)
    return success(view_appointment(a), 200)


@app.route("/appointments/<aid>/complete", methods=["POST"])
def complete_appointment(aid):
    role, uid = get_identity()
    require_roles(role, {"Therapist"})
    a = get_or_404(db.appointments, aid)
    if uid != a["therapist_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "not the rendering therapist")

    if a["status"] != "RENDERED":
        raise ApiError("ERR_INVALID_STATE", "complete not defined from this state")

    note = note_for_appointment(aid)
    therapist = db.therapists[a["therapist_id"]]
    # State precondition: a note must exist in SIGNED or CO_SIGNED status.
    if note is None or note["status"] not in {"SIGNED", "CO_SIGNED"}:
        raise ApiError("ERR_INVALID_STATE", "a SIGNED or CO_SIGNED note is required")
    # Supervision gate (priority 13): supervised therapist's note must be CO_SIGNED.
    if therapist["requires_supervision"] and note["status"] != "CO_SIGNED":
        raise ApiError("ERR_COSIGN_REQUIRED", "co-signed note required")

    a["status"] = "COMPLETED"
    touch(a)
    therapist["verified_direct_hours"] = recompute_verified_direct_hours(a["therapist_id"])
    touch(therapist)
    return success(view_appointment(a), 200)


@app.route("/appointments/<aid>/write-off", methods=["POST"])
def writeoff_appointment(aid):
    role, uid = get_identity()
    require_roles(role, {"Biller"})
    a = get_or_404(db.appointments, aid)
    if a["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", "write-off not defined from this state")
    if a["payment_path"] != "SELF_PAY":
        raise ApiError("ERR_INVALID_STATE", "write-off only for self-pay")
    a["status"] = "WRITTEN_OFF"
    a["patient_charge_cents"] = 0
    touch(a)
    return success(view_appointment(a), 200)


@app.route("/appointments/<aid>/cancel", methods=["POST"])
def cancel_appointment(aid):
    role, uid = get_identity()
    require_roles(role, {"FrontDesk", "ClinicalDirector"})
    a = get_or_404(db.appointments, aid)
    if a["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "cancel not defined from this state")
    a["status"] = "CANCELLED"
    touch(a)
    return success(view_appointment(a), 200)


# ===========================================================================
# CLINICAL NOTE
# ===========================================================================
@app.route("/clinical-notes", methods=["POST"])
def create_note():
    role, uid = get_identity()
    require_roles(role, {"Therapist"})
    body = get_body()
    require_fields(body, ["appointment_id", "narrative"])
    appointment_id = require_str(body, "appointment_id")
    narrative = require_str(body, "narrative")
    get_or_404(db.appointments, appointment_id)
    n = new_base()
    n.update({
        "appointment_id": appointment_id,
        "narrative": narrative,
        "status": "DRAFT",
        "signed_by_id": None,
        "cosigned_by_id": None,
    })
    db.clinical_notes[n["id"]] = n
    return success(view_note(n), 201)


@app.route("/clinical-notes/<nid>", methods=["GET"])
def get_note(nid):
    role, uid = get_identity()
    require_roles(role, {"Therapist", "ClinicalDirector"})
    n = get_or_404(db.clinical_notes, nid)
    return success(view_note(n), 200)


@app.route("/clinical-notes", methods=["GET"])
def list_notes():
    role, uid = get_identity()
    require_roles(role, {"Therapist", "ClinicalDirector"})
    items = list(db.clinical_notes.values())
    for key in ("appointment_id", "signed_by_id", "cosigned_by_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [n for n in items if n[key] == val]
    page, pg = paginate(items)
    return success([view_note(n) for n in page], 200, "array", pg)


@app.route("/clinical-notes/<nid>/sign", methods=["POST"])
def sign_note(nid):
    role, uid = get_identity()
    require_roles(role, {"Therapist"})
    n = get_or_404(db.clinical_notes, nid)
    appt = db.appointments.get(n["appointment_id"])
    # ownership: acting therapist must be the rendering therapist of linked appointment
    if appt is None or uid != appt["therapist_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "not the rendering therapist")
    if n["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "sign not defined from this state")
    n["status"] = "SIGNED"
    n["signed_by_id"] = uid
    touch(n)
    return success(view_note(n), 200)


@app.route("/clinical-notes/<nid>/cosign", methods=["POST"])
def cosign_note(nid):
    role, uid = get_identity()
    require_roles(role, {"Therapist"})
    n = get_or_404(db.clinical_notes, nid)
    appt = db.appointments.get(n["appointment_id"])
    if appt is None:
        raise ApiError("ERR_NOT_FOUND", "appointment not found")
    rendering = db.therapists.get(appt["therapist_id"])
    # ownership: acting therapist must be the rendering therapist's supervisor
    if rendering is None or rendering["supervisor_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "not the supervisor")
    if n["status"] != "SIGNED":
        raise ApiError("ERR_INVALID_STATE", "cosign not defined from this state")
    actor = db.therapists.get(uid)
    if actor is None or actor["credential_status"] != "INDEPENDENT":
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "co-signer must be INDEPENDENT")
    n["status"] = "CO_SIGNED"
    n["cosigned_by_id"] = uid
    touch(n)
    return success(view_note(n), 200)


# ===========================================================================
# CLAIM
# ===========================================================================
def compute_insurance_responsibility(claim, policy, contract):
    cpt = claim["cpt_code"]
    std = STD_RATE_CENTS[cpt]
    billed = std
    if contract["in_network"]:
        contracted = contract["contracted_rate_90791_cents"] if cpt == "90791" \
            else contract["contracted_rate_90834_cents"]
        allowed = min(billed, contracted)
    else:
        allowed = billed
    remaining_deductible = max(0, policy["deductible_total_cents"] - policy["deductible_met_cents"])
    deductible_applied = min(allowed, remaining_deductible)
    after_deductible = allowed - deductible_applied
    if policy["cost_share_model"] == "COPAY":
        cost_share = min(policy["copay_cents"], after_deductible)
    else:
        cost_share = round_cents(Decimal(after_deductible) * Decimal(str(policy["coinsurance_rate"])))
    patient_resp = deductible_applied + cost_share
    payer_paid = allowed - patient_resp
    return {
        "allowed_amount_cents": allowed,
        "deductible_applied_cents": deductible_applied,
        "patient_responsibility_cents": patient_resp,
        "payer_paid_cents": payer_paid,
    }


@app.route("/claims", methods=["POST"])
def create_claim():
    role, uid = get_identity()
    require_roles(role, {"Biller"})
    body = get_body()
    require_fields(body, ["appointment_id", "expected_appointment_version"])
    appointment_id = require_str(body, "appointment_id")
    exp_v = require_int(body, "expected_appointment_version")

    a = get_or_404(db.appointments, appointment_id)

    # state: appointment must be COMPLETED to fork to CLAIMED
    if a["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", "appointment not COMPLETED")
    # payment path must be INSURANCE — modeled as a precondition for the transition
    if a["payment_path"] != "INSURANCE":
        raise ApiError("ERR_INVALID_STATE", "appointment is not on INSURANCE path")

    # one-live-claim (priority 17)
    for c in db.claims.values():
        if c["appointment_id"] == appointment_id and c["status"] != "VOID":
            raise ApiError("ERR_CLAIM_ALREADY_EXISTS", "appointment already has a live claim")

    # OCC (priority 18, last)
    if exp_v != a["version"]:
        raise ApiError("ERR_STALE_VERSION", "appointment version mismatch")

    std = STD_RATE_CENTS[a["cpt_code"]]
    c = new_base()
    c.update({
        "appointment_id": appointment_id,
        "insurance_policy_id": a["insurance_policy_id"],
        "cpt_code": a["cpt_code"],
        "billed_charge_cents": std,
        "allowed_amount_cents": 0,
        "deductible_applied_cents": 0,
        "patient_responsibility_cents": 0,
        "payer_paid_cents": 0,
        "status": "SUBMITTED",
    })
    db.claims[c["id"]] = c
    # cascade: appointment COMPLETED -> CLAIMED, version bump
    a["status"] = "CLAIMED"
    touch(a)
    return success(view_claim(c), 201)


@app.route("/claims/<cid>", methods=["GET"])
def get_claim(cid):
    role, uid = get_identity()
    require_roles(role, {"Biller", "ClinicalDirector"})
    c = get_or_404(db.claims, cid)
    return success(view_claim(c), 200)


@app.route("/claims", methods=["GET"])
def list_claims():
    role, uid = get_identity()
    require_roles(role, {"Biller", "ClinicalDirector"})
    items = list(db.claims.values())
    for key in ("appointment_id", "insurance_policy_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c[key] == val]
    page, pg = paginate(items)
    return success([view_claim(c) for c in page], 200, "array", pg)


@app.route("/claims/<cid>/adjudicate", methods=["POST"])
def adjudicate_claim(cid):
    role, uid = get_identity()
    require_roles(role, {"Biller"})
    c = get_or_404(db.claims, cid)
    body = get_body()
    require_fields(body, ["expected_claim_version"])
    exp_v = require_int(body, "expected_claim_version")
    if c["status"] not in {"SUBMITTED", "RESUBMITTED"}:
        raise ApiError("ERR_INVALID_STATE", "adjudicate not defined from this state")
    if exp_v != c["version"]:
        raise ApiError("ERR_STALE_VERSION", "claim version mismatch")

    policy = db.insurance_policies[c["insurance_policy_id"]]
    contract = db.payer_contracts[policy["contract_id"]]
    result = compute_insurance_responsibility(c, policy, contract)
    c["allowed_amount_cents"] = result["allowed_amount_cents"]
    c["deductible_applied_cents"] = result["deductible_applied_cents"]
    c["patient_responsibility_cents"] = result["patient_responsibility_cents"]
    c["payer_paid_cents"] = result["payer_paid_cents"]
    c["status"] = "ADJUDICATED"
    touch(c)
    # cascade: policy deductible_met += applied
    policy["deductible_met_cents"] += result["deductible_applied_cents"]
    touch(policy)
    # cascade: appointment patient_charge_cents = patient_responsibility
    appt = db.appointments.get(c["appointment_id"])
    if appt is not None:
        appt["patient_charge_cents"] = result["patient_responsibility_cents"]
        touch(appt)
    return success(view_claim(c), 200)


@app.route("/claims/<cid>/deny", methods=["POST"])
def deny_claim(cid):
    role, uid = get_identity()
    require_roles(role, {"Biller"})
    c = get_or_404(db.claims, cid)
    body = get_body()
    require_fields(body, ["expected_claim_version"])
    exp_v = require_int(body, "expected_claim_version")
    if c["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "deny not defined from this state")
    if exp_v != c["version"]:
        raise ApiError("ERR_STALE_VERSION", "claim version mismatch")
    c["status"] = "DENIED"
    touch(c)
    return success(view_claim(c), 200)


@app.route("/claims/<cid>/resubmit", methods=["POST"])
def resubmit_claim(cid):
    role, uid = get_identity()
    require_roles(role, {"Biller"})
    c = get_or_404(db.claims, cid)
    body = get_body()
    require_fields(body, ["expected_claim_version"])
    exp_v = require_int(body, "expected_claim_version")
    if c["status"] != "DENIED":
        raise ApiError("ERR_INVALID_STATE", "resubmit not defined from this state")
    if exp_v != c["version"]:
        raise ApiError("ERR_STALE_VERSION", "claim version mismatch")
    c["status"] = "RESUBMITTED"
    touch(c)
    return success(view_claim(c), 200)


@app.route("/claims/<cid>/void", methods=["POST"])
def void_claim(cid):
    role, uid = get_identity()
    require_roles(role, {"Biller"})
    c = get_or_404(db.claims, cid)
    body = get_body()
    require_fields(body, ["expected_claim_version"])
    exp_v = require_int(body, "expected_claim_version")
    if c["status"] != "ADJUDICATED":
        raise ApiError("ERR_INVALID_STATE", "void not defined from this state")
    if exp_v != c["version"]:
        raise ApiError("ERR_STALE_VERSION", "claim version mismatch")
    # compensating reversal
    policy = db.insurance_policies.get(c["insurance_policy_id"])
    if policy is not None:
        policy["deductible_met_cents"] -= c["deductible_applied_cents"]
        touch(policy)
    appt = db.appointments.get(c["appointment_id"])
    if appt is not None:
        appt["patient_charge_cents"] = 0
        appt["status"] = "COMPLETED"
        touch(appt)
    c["status"] = "VOID"
    touch(c)
    return success(view_claim(c), 200)


# ===========================================================================
# CRISIS ASSESSMENT
# ===========================================================================
@app.route("/crisis-assessments", methods=["POST"])
def create_crisis():
    role, uid = get_identity()
    require_roles(role, {"Therapist", "ClinicalDirector"})
    body = get_body()
    require_fields(body, ["patient_id", "therapist_id", "ideation_score",
                          "plan_score", "means_access_score", "prior_attempts_score"])
    patient_id = require_str(body, "patient_id")
    therapist_id = require_str(body, "therapist_id")
    ideation = require_int(body, "ideation_score", 0, 3)
    plan = require_int(body, "plan_score", 0, 3)
    means = require_int(body, "means_access_score", 0, 3)
    prior = require_int(body, "prior_attempts_score", 0, 3)

    patient = get_or_404(db.patients, patient_id)
    get_or_404(db.therapists, therapist_id)

    if patient["status"] == "DISCHARGED":
        raise ApiError("ERR_INVALID_STATE", "patient is discharged")

    score, band = compute_crisis_risk(ideation, plan, means, prior)
    c = new_base()
    c.update({
        "patient_id": patient_id,
        "therapist_id": therapist_id,
        "ideation_score": ideation,
        "plan_score": plan,
        "means_access_score": means,
        "prior_attempts_score": prior,
        "risk_score": score,
        "risk_band": band,
        "status": "OPEN",
    })
    db.crisis_assessments[c["id"]] = c
    if band == "HIGH":
        patient["status"] = "ON_CLINICAL_HOLD"
        touch(patient)
    return success(view_crisis(c), 201)


@app.route("/crisis-assessments/<cid>", methods=["GET"])
def get_crisis(cid):
    role, uid = get_identity()
    require_roles(role, {"Therapist", "ClinicalDirector"})
    c = get_or_404(db.crisis_assessments, cid)
    return success(view_crisis(c), 200)


@app.route("/crisis-assessments", methods=["GET"])
def list_crisis():
    role, uid = get_identity()
    require_roles(role, {"Therapist", "ClinicalDirector"})
    items = list(db.crisis_assessments.values())
    for key in ("patient_id", "therapist_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c[key] == val]
    page, pg = paginate(items)
    return success([view_crisis(c) for c in page], 200, "array", pg)


@app.route("/crisis-assessments/<cid>/resolve", methods=["POST"])
def resolve_crisis(cid):
    role, uid = get_identity()
    require_roles(role, {"Therapist", "ClinicalDirector"})
    c = get_or_404(db.crisis_assessments, cid)
    if c["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "resolve not defined from this state")
    # safety-plan gate (priority 9)
    if c["risk_band"] == "HIGH":
        has_plan = any(sp["crisis_assessment_id"] == cid for sp in db.safety_plans.values())
        if not has_plan:
            raise ApiError("ERR_SAFETY_PLAN_REQUIRED", "safety plan required to resolve")
    c["status"] = "RESOLVED"
    touch(c)
    # cascade: lift hold if no other OPEN assessment for patient
    other_open = any(
        ca["patient_id"] == c["patient_id"] and ca["status"] == "OPEN" and ca["id"] != cid
        for ca in db.crisis_assessments.values()
    )
    if not other_open:
        patient = db.patients.get(c["patient_id"])
        if patient is not None and patient["status"] == "ON_CLINICAL_HOLD":
            patient["status"] = "ACTIVE"
            touch(patient)
    return success(view_crisis(c), 200)


# ===========================================================================
# SAFETY PLAN
# ===========================================================================
@app.route("/safety-plans", methods=["POST"])
def create_safety_plan():
    role, uid = get_identity()
    require_roles(role, {"Therapist", "ClinicalDirector"})
    body = get_body()
    require_fields(body, ["crisis_assessment_id", "warning_signs",
                          "coping_strategies", "emergency_contacts"])
    crisis_assessment_id = require_str(body, "crisis_assessment_id")
    warning_signs = require_str(body, "warning_signs")
    coping = require_str(body, "coping_strategies")
    contacts = body.get("emergency_contacts")
    if not isinstance(contacts, list) or len(contacts) == 0:
        raise ApiError("ERR_INVALID_REQUEST", "emergency_contacts must be a non-empty array")

    get_or_404(db.crisis_assessments, crisis_assessment_id)

    sp = new_base()
    sp.update({
        "crisis_assessment_id": crisis_assessment_id,
        "warning_signs": warning_signs,
        "coping_strategies": coping,
        "emergency_contacts": contacts,
    })
    db.safety_plans[sp["id"]] = sp
    return success(view_safety(sp), 201)


@app.route("/safety-plans/<sid>", methods=["GET"])
def get_safety_plan(sid):
    role, uid = get_identity()
    require_roles(role, {"Therapist", "ClinicalDirector"})
    sp = get_or_404(db.safety_plans, sid)
    return success(view_safety(sp), 200)


@app.route("/safety-plans", methods=["GET"])
def list_safety_plans():
    role, uid = get_identity()
    require_roles(role, {"Therapist", "ClinicalDirector"})
    items = list(db.safety_plans.values())
    caid = request.args.get("crisis_assessment_id")
    if caid is not None:
        items = [sp for sp in items if sp["crisis_assessment_id"] == caid]
    page, pg = paginate(items)
    return success([view_safety(sp) for sp in page], 200, "array", pg)


# ===========================================================================
# TEST-DRIVING ENDPOINTS
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role, uid = get_identity()
    require_roles(role, {"ClinicalDirector"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    try:
        db.current_utc = parse_dt(body["to_iso8601"])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be ISO 8601")
    return success({}, 200)


@app.route("/_inject/therapist_hours", methods=["POST"])
def inject_hours():
    role, uid = get_identity()
    require_roles(role, {"ClinicalDirector"})
    body = get_body()
    require_fields(body, ["therapist_id", "verified_direct_hours", "verified_supervision_hours"])
    therapist_id = require_str(body, "therapist_id")
    vdh = require_number(body, "verified_direct_hours", min_v=0)
    vsh = require_number(body, "verified_supervision_hours", min_v=0)
    t = get_or_404(db.therapists, therapist_id)
    t["verified_direct_hours"] = vdh
    t["verified_supervision_hours"] = vsh
    touch(t)
    return success(view_therapist(t), 200)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    meta = make_meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    meta = make_meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    meta = make_meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    meta = make_meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": str(e)},
    }
    return jsonify(body), 422


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
