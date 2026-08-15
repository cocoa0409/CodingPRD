"""All API endpoints for the Outpatient Clinic Registration API.

Validation order on every request (PRD section 2.10 / SCAFFOLD section 1.4):
  1. auth headers (401)          -- handled by @authed
  2. role permission (403)       -- handled by @authed
  3. path existence (404)        -- left to right
  4. structural body check (400) -- required fields / types / enums / ranges
  5. body reference existence (404)
  6. OCC where declared (412)
  7. state transition admissibility (409)
  8. business rules in the order pinned by PRD section 3
"""
from datetime import timedelta

from flask import Blueprint

from store import db
from core import (
    ApiError, authed, body, ok_object, ok_list, paginate, serialize,
    new_record, touch, get_or_404, now, iso,
    v_str, v_enum, v_int, v_bool, v_date, v_datetime, parse_d,
)
from domain import (
    LATE_ARRIVAL_CUTOFF_MINUTES, NO_SHOW_GRACE_MINUTES, PRE_ARRIVAL_STATES,
    strike_count, propagate_strikes, refresh_staleness, latest_fresh_check,
    latest_estimate, latest_provisional_estimate, satisfying_auth,
    compute_clearance, recompute_clearance, run_matching, rematch_patient_unmatched,
    recompute_collected, estimate_amounts, repin_cached_estimate,
    double_booked, expire_timeboxed,
)

bp = Blueprint("patient_access", __name__, url_prefix="/patient-access")

ALL4 = ("Registrar", "FinancialCounselor", "FrontDeskAgent", "AccessSupervisor")
REG_FC_SUP = ("Registrar", "FinancialCounselor", "AccessSupervisor")

SEX_VALUES = ("M", "F", "X")
PLAN_TYPES = ("HMO", "PPO", "EPO", "POS", "MEDICARE", "MEDICAID", "SELF_PAY")
COVERAGE_STATUSES = ("ACTIVE", "INACTIVE", "NOT_FOUND", "UNKNOWN")
VISIT_TYPES = ("NEW", "ESTABLISHED", "PROCEDURE", "IMAGING")
PAYMENT_METHODS = ("CASH", "CARD", "CHECK", "WALLET")
PAYMENT_KINDS = ("POST", "REFUND")
FLAG_TYPES = ("INTERPRETER", "MOBILITY", "SENSORY", "COGNITIVE")


# ================================================================= logical clock
@bp.post("/_clock/set_current_utc")
@authed("AccessSupervisor")
def set_clock():
    b = body()
    dt = v_datetime(b, "to_iso8601")
    db.clock = dt
    expire_timeboxed()
    return ok_object({"current_utc": iso(dt)})


# ===================================================================== patients
@bp.post("/patients")
@authed("Registrar")
def create_patient():
    b = body()
    first_name = v_str(b, "first_name")
    last_name = v_str(b, "last_name")
    dob = v_date(b, "date_of_birth")
    sex = v_enum(b, "sex_at_birth", SEX_VALUES)
    phone = v_str(b, "primary_phone")
    email = v_str(b, "email", required=False)
    language = v_str(b, "language_code", required=False) or "en"
    # duplicate prevention: exact name/dob triple or phone, ignoring MERGED records
    for p in db.patients.values():
        if p["status"] == "MERGED":
            continue
        if ((p["first_name"] == first_name and p["last_name"] == last_name
                and p["date_of_birth"] == dob) or p["primary_phone"] == phone):
            raise ApiError("ERR_DUPLICATE_PATIENT", 409,
                           "an existing patient matches these demographics")
    rec = new_record()
    rec.update({
        "mrn": db.next_mrn(),
        "first_name": first_name,
        "last_name": last_name,
        "date_of_birth": dob,
        "sex_at_birth": sex,
        "primary_phone": phone,
        "email": email,
        "language_code": language,
        "duplicate_of_patient_id": None,
        "status": "PRE_REGISTERED",
        "consent_general": None,
        "consent_financial": None,
    })
    db.patients[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/patients")
@authed(*ALL4)
def list_patients():
    items = list(db.patients.values())
    status = request_arg("status")
    last_name = request_arg("last_name")
    dob = request_arg("date_of_birth")
    dup = request_arg("duplicate_of_patient_id")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if last_name is not None:
        items = [p for p in items if p["last_name"] == last_name]
    if dob is not None:
        items = [p for p in items if p["date_of_birth"] == dob]
    if dup is not None:
        items = [p for p in items if p["duplicate_of_patient_id"] == dup]
    page, pmeta = paginate(items)
    return ok_list(page, pmeta)


def request_arg(name):
    from flask import request as _req
    v = _req.args.get(name)
    return v if v not in (None, "") else None


@bp.get("/patients/<pid>")
@authed(*ALL4)
def get_patient(pid):
    return ok_object(serialize(get_or_404("patients", pid, "patient")))


@bp.post("/patients/<pid>/complete-registration")
@authed("Registrar")
def complete_registration(pid):
    patient = get_or_404("patients", pid, "patient")
    b = body()
    consent_general = v_bool(b, "consent_general")
    consent_financial = v_bool(b, "consent_financial", required=False)
    phone = v_str(b, "primary_phone", required=False)
    email = v_str(b, "email", required=False)
    if patient["status"] != "PRE_REGISTERED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "patient is not in PRE_REGISTERED status")
    for f in ("first_name", "last_name", "date_of_birth", "sex_at_birth", "primary_phone"):
        if not patient[f]:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "demographic completeness requires '%s'" % f)
    if consent_general is not True:
        raise ApiError("ERR_INVALID_REQUEST", 400, "consent_general must be true")
    patient["consent_general"] = True
    if consent_financial is not None:
        patient["consent_financial"] = consent_financial
    if phone is not None:
        patient["primary_phone"] = phone
    if email is not None:
        patient["email"] = email
    patient["status"] = "REGISTERED"
    touch(patient)
    for a in db.appointments.values():
        if a["patient_id"] == pid and a["status"] == "SCHEDULED":
            recompute_clearance(a)
    return ok_object(serialize(patient))


@bp.post("/patients/<pid>/merge")
@authed("Registrar")
def merge_patient(pid):
    patient = get_or_404("patients", pid, "patient")
    b = body()
    survivor_id = v_str(b, "survivor_patient_id")
    expected = v_int(b, "expected_patient_version")
    survivor = get_or_404("patients", survivor_id, "survivor patient")
    if survivor["id"] == patient["id"]:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "survivor_patient_id must reference a different patient")
    if expected != patient["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_patient_version does not match current version")
    if patient["status"] not in ("PRE_REGISTERED", "REGISTERED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only PRE_REGISTERED or REGISTERED patients can be merged")
    if survivor["status"] == "MERGED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "survivor patient must not be MERGED")
    patient["duplicate_of_patient_id"] = survivor["id"]
    patient["status"] = "MERGED"
    touch(patient)
    for a in db.appointments.values():
        if a["patient_id"] == pid and a["status"] in PRE_ARRIVAL_STATES:
            a["patient_id"] = survivor["id"]
            run_matching(a)
            recompute_clearance(a)
            touch(a)
    for pol in db.policies.values():
        if pol["patient_id"] == pid:
            pol["patient_id"] = survivor["id"]
            touch(pol)
    return ok_object(serialize(patient))


@bp.post("/patients/<pid>/deactivate")
@authed("AccessSupervisor")
def deactivate_patient(pid):
    patient = get_or_404("patients", pid, "patient")
    if patient["status"] != "REGISTERED":
        raise ApiError("ERR_INVALID_STATE", 409, "patient is not REGISTERED")
    for a in db.appointments.values():
        if a["patient_id"] == pid and a["status"] in (
                "SCHEDULED", "PRE_CHECKED", "READY", "ARRIVED", "IN_ROOM"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "patient has live appointments and cannot be deactivated")
    patient["status"] = "INACTIVE"
    touch(patient)
    return ok_object(serialize(patient))


# ------------------------------------------------------ patient reverse lookups
@bp.get("/patients/<pid>/appointments")
@authed(*ALL4)
def patient_appointments(pid):
    get_or_404("patients", pid, "patient")
    items = [a for a in db.appointments.values() if a["patient_id"] == pid]
    status = request_arg("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, pmeta = paginate(items)
    return ok_list(page, pmeta)


@bp.get("/patients/<pid>/insurance-policies")
@authed(*REG_FC_SUP)
def patient_policies(pid):
    get_or_404("patients", pid, "patient")
    items = [p for p in db.policies.values() if p["patient_id"] == pid]
    status = request_arg("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, pmeta = paginate(items)
    return ok_list(page, pmeta)


@bp.get("/patients/<pid>/referrals")
@authed(*REG_FC_SUP)
def patient_referrals(pid):
    get_or_404("patients", pid, "patient")
    items = [r for r in db.referrals.values() if r["patient_id"] == pid]
    status = request_arg("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, pmeta = paginate(items)
    return ok_list(page, pmeta)


@bp.get("/patients/<pid>/authorizations")
@authed(*REG_FC_SUP)
def patient_authorizations(pid):
    get_or_404("patients", pid, "patient")
    items = [a for a in db.authorizations.values() if a["patient_id"] == pid]
    status = request_arg("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, pmeta = paginate(items)
    return ok_list(page, pmeta)


@bp.get("/patients/<pid>/accommodation-flags")
@authed("Registrar", "FrontDeskAgent", "AccessSupervisor")
def patient_flags(pid):
    get_or_404("patients", pid, "patient")
    items = [f for f in db.flags.values() if f["patient_id"] == pid]
    active = request_arg("active")
    if active is not None and active.lower() in ("true", "false"):
        want = active.lower() == "true"
        items = [f for f in items if f["active"] == want]
    page, pmeta = paginate(items)
    return ok_list(page, pmeta)


# ============================================================ accommodation flags
@bp.post("/patients/<pid>/accommodation-flags")
@authed("Registrar")
def create_flag(pid):
    get_or_404("patients", pid, "patient")
    b = body()
    flag_type = v_enum(b, "flag_type", FLAG_TYPES)
    language = v_str(b, "language_code", required=False)
    note = v_str(b, "note", required=False)
    if flag_type == "INTERPRETER" and language is None:
        raise ApiError("ERR_LANGUAGE_REQUIRED", 400,
                       "INTERPRETER flag requires language_code")
    rec = new_record()
    rec.update({
        "patient_id": pid,
        "flag_type": flag_type,
        "language_code": language,
        "note": note,
        "active": True,
    })
    db.flags[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.post("/accommodation-flags/<fid>/deactivate")
@authed("Registrar", "AccessSupervisor")
def deactivate_flag(fid):
    flag = get_or_404("flags", fid, "accommodation flag")
    if flag["active"]:
        flag["active"] = False
        touch(flag)
    return ok_object(serialize(flag))


# ============================================================ insurance policies
@bp.post("/insurance-policies")
@authed("Registrar")
def create_policy():
    b = body()
    patient_id = v_str(b, "patient_id")
    payer_id = v_str(b, "payer_id")
    member_id = v_str(b, "member_id")
    group_number = v_str(b, "group_number", required=False)
    plan_type = v_enum(b, "plan_type", PLAN_TYPES)
    effective_start = v_date(b, "effective_start")
    effective_end = v_date(b, "effective_end", required=False)
    priority_rank = v_int(b, "priority_rank", minv=1)
    ded = v_int(b, "deductible_remaining_cents", minv=0)
    oop = v_int(b, "oop_max_remaining_cents", minv=0)
    get_or_404("patients", patient_id, "patient")
    # date-range rule is evaluated before rank uniqueness (PRD section 3.2)
    if effective_end is not None and parse_d(effective_end) < parse_d(effective_start):
        raise ApiError("ERR_INVALID_DATE_RANGE", 400,
                       "effective_end must not precede effective_start")
    for p in db.policies.values():
        if (p["patient_id"] == patient_id and p["status"] != "VOIDED"
                and p["priority_rank"] == priority_rank):
            raise ApiError("ERR_PRIORITY_RANK_CONFLICT", 409,
                           "priority_rank already used by a non-VOIDED policy")
    rec = new_record()
    rec.update({
        "patient_id": patient_id,
        "payer_id": payer_id,
        "member_id": member_id,
        "group_number": group_number,
        "plan_type": plan_type,
        "effective_start": effective_start,
        "effective_end": effective_end,
        "priority_rank": priority_rank,
        "deductible_remaining_cents": ded,
        "oop_max_remaining_cents": oop,
        "status": "ACTIVE",
    })
    db.policies[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/insurance-policies/<pid>")
@authed(*REG_FC_SUP)
def get_policy(pid):
    return ok_object(serialize(get_or_404("policies", pid, "insurance policy")))


@bp.get("/insurance-policies/<pid>/eligibility-checks")
@authed(*REG_FC_SUP)
def policy_checks(pid):
    get_or_404("policies", pid, "insurance policy")
    items = [c for c in db.eligibility_checks.values() if c["policy_id"] == pid]
    for c in items:
        refresh_staleness(c)
    page, pmeta = paginate(items)
    return ok_list(page, pmeta)


@bp.get("/insurance-policies/<pid>/copay-estimates")
@authed(*REG_FC_SUP)
def policy_estimates(pid):
    get_or_404("policies", pid, "insurance policy")
    items = [e for e in db.estimates.values() if e["policy_id"] == pid]
    status = request_arg("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, pmeta = paginate(items)
    return ok_list(page, pmeta)


@bp.post("/insurance-policies/<pid>/terminate")
@authed("Registrar")
def terminate_policy(pid):
    policy = get_or_404("policies", pid, "insurance policy")
    b = body()
    effective_end = v_date(b, "effective_end")
    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "policy is not ACTIVE")
    if parse_d(effective_end) < parse_d(policy["effective_start"]):
        raise ApiError("ERR_INVALID_DATE_RANGE", 400,
                       "effective_end must not precede effective_start")
    policy["effective_end"] = effective_end
    policy["status"] = "TERMINATED"
    touch(policy)
    # cascade: provisional estimates built on this policy -> SUPERSEDED
    for est in db.estimates.values():
        if est["policy_id"] == pid and est["status"] == "PROVISIONAL":
            appt = db.appointments.get(est["appointment_id"])
            if (appt is not None and appt["patient_id"] == policy["patient_id"]
                    and appt["status"] in ("SCHEDULED", "PRE_CHECKED")):
                est["status"] = "SUPERSEDED"
                touch(est)
                repin_cached_estimate(appt)
                recompute_clearance(appt)
    return ok_object(serialize(policy))


@bp.post("/insurance-policies/<pid>/void")
@authed("AccessSupervisor")
def void_policy(pid):
    policy = get_or_404("policies", pid, "insurance policy")
    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "policy is not ACTIVE")
    for c in db.eligibility_checks.values():
        if c["policy_id"] == pid and c["coverage_status"] == "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "policy has an ACTIVE eligibility check and cannot be voided")
    policy["status"] = "VOIDED"
    touch(policy)
    return ok_object(serialize(policy))


# ==================================================================== referrals
@bp.post("/referrals")
@authed("Registrar")
def create_referral():
    b = body()
    patient_id = v_str(b, "patient_id")
    npi = v_str(b, "referring_provider_npi")
    specialty = v_str(b, "specialty_code")
    procedure = v_str(b, "procedure_code")
    visits = v_int(b, "visits_authorized", minv=1)
    valid_from = v_date(b, "valid_from")
    valid_until = v_date(b, "valid_until")
    get_or_404("patients", patient_id, "patient")
    if parse_d(valid_from) > parse_d(valid_until):
        raise ApiError("ERR_INVALID_DATE_RANGE", 400,
                       "valid_from must not follow valid_until")
    rec = new_record()
    rec.update({
        "patient_id": patient_id,
        "referring_provider_npi": npi,
        "specialty_code": specialty,
        "procedure_code": procedure,
        "visits_authorized": visits,
        "visits_consumed": 0,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "status": "OPEN",
    })
    db.referrals[rec["id"]] = rec
    rematch_patient_unmatched(patient_id)
    return ok_object(serialize(rec), 201)


@bp.get("/referrals/<rid>")
@authed(*REG_FC_SUP)
def get_referral(rid):
    return ok_object(serialize(get_or_404("referrals", rid, "referral")))


@bp.post("/referrals/<rid>/close")
@authed("Registrar")
def close_referral(rid):
    ref = get_or_404("referrals", rid, "referral")
    if ref["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "referral is not OPEN")
    ref["status"] = "CLOSED"
    touch(ref)
    return ok_object(serialize(ref))


# =============================================================== authorizations
@bp.post("/authorizations")
@authed("Registrar")
def create_authorization():
    b = body()
    patient_id = v_str(b, "patient_id")
    appointment_id = v_str(b, "appointment_id")
    auth_number = v_str(b, "payer_auth_number")
    units = v_int(b, "authorized_units", minv=1)
    valid_until = v_date(b, "valid_until")
    get_or_404("patients", patient_id, "patient")
    appt = get_or_404("appointments", appointment_id, "appointment")
    rec = new_record()
    rec.update({
        "patient_id": patient_id,
        "appointment_id": appointment_id,
        "payer_auth_number": auth_number,
        "authorized_units": units,
        "valid_until": valid_until,
        "status": "APPROVED",
    })
    db.authorizations[rec["id"]] = rec
    recompute_clearance(appt)
    return ok_object(serialize(rec), 201)


@bp.get("/authorizations/<aid>")
@authed(*REG_FC_SUP)
def get_authorization(aid):
    return ok_object(serialize(get_or_404("authorizations", aid, "authorization")))


@bp.get("/appointments/<aid>/authorizations")
@authed(*REG_FC_SUP)
def appointment_authorizations(aid):
    get_or_404("appointments", aid, "appointment")
    items = [a for a in db.authorizations.values() if a["appointment_id"] == aid]
    status = request_arg("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, pmeta = paginate(items)
    return ok_list(page, pmeta)


@bp.post("/authorizations/<aid>/void")
@authed("AccessSupervisor")
def void_authorization(aid):
    auth = get_or_404("authorizations", aid, "authorization")
    if auth["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "authorization is not APPROVED")
    auth["status"] = "VOIDED"
    touch(auth)
    appt = db.appointments.get(auth["appointment_id"])
    if appt is not None:
        recompute_clearance(appt)
    return ok_object(serialize(auth))
