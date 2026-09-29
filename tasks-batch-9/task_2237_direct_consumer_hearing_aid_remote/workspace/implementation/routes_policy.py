"""State policies, patients, screening sessions, findings and compliance overrides."""

from flask import Blueprint

import calc
import services as svc
from auth import (ADMIN, CARE_OPS, COMPLIANCE, HEARING_PROFESSIONAL, LICENSED_AUDIOLOGIST,
                  PATIENT, REIMBURSEMENT, authorize, require_audiologist, require_distinct_user,
                  require_owner)
from bodyspec import Body, raw_body
from common import field, listed
from errors import ApiError
from resp import created, ok
from store import bump, db, days, now, table_rows

bp = Blueprint("policy", __name__)

RESTOCKING_MODES = ("FLAT_PCT", "PRORATED_DAILY", "PROHIBITED")
PATIENT_STATUSES = ("REGISTERED", "SCREENING_IN_PROGRESS", "CANDIDATE_APPROVED",
                    "REFERRAL_REQUIRED", "PROVIDER_CLEARED", "MEDICALLY_DISQUALIFIED",
                    "DEACTIVATED")
RISK_BANDS = ("LOW", "MODERATE", "HIGH")


def check_ref(name, table, data=None):
    data = raw_body() if data is None else data
    value = data.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    row = table.get(value)
    if row is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    return row


# --------------------------------------------------------------- StatePolicy
@bp.post("/state-policies")
def create_state_policy():
    authorize(ADMIN)
    body = Body()
    state_code = body.string("state_code", min_len=2, max_len=2)
    otc = body.boolean("otc_sales_permitted", required=False, default=True)
    telehealth = body.boolean("telehealth_fitting_permitted", required=False, default=True)
    min_age = body.integer("min_age_years", required=False, default=18, minimum=0, maximum=120)
    trial_days = body.integer("trial_period_days", minimum=30, maximum=90)
    mode = body.enum("restocking_fee_mode", RESTOCKING_MODES)
    pct = body.number("restocking_fee_pct", required=False, default=0, minimum=0, maximum=0.20)
    daily = body.integer("restocking_daily_rate_cents", required=False, default=0, minimum=0)
    cap = body.integer("restocking_fee_cap_cents", required=False, default=0, minimum=0)
    shipping_refundable = body.boolean("shipping_refundable", required=False, default=False)
    validity = body.integer("referral_validity_days", required=False, default=180, minimum=0)
    waiver = body.boolean("waiver_required", required=False, default=False)
    max_claims = body.integer("max_loss_damage_claims", required=False, default=2, minimum=0)
    body.finish()
    if state_code != state_code.upper():
        raise ApiError("ERR_VALIDATION", "state_code must be uppercase")
    for row in db.state_policies.values():
        if row["state_code"] == state_code:
            raise ApiError("ERR_DUPLICATE_KEY")
    policy = svc.new_row(
        db.state_policies,
        state_code=state_code, otc_sales_permitted=otc,
        telehealth_fitting_permitted=telehealth, min_age_years=min_age,
        trial_period_days=trial_days, restocking_fee_mode=mode,
        restocking_fee_pct=pct, restocking_daily_rate_cents=daily,
        restocking_fee_cap_cents=cap, shipping_refundable=shipping_refundable,
        referral_validity_days=validity, waiver_required=waiver,
        max_loss_damage_claims=max_claims, is_retired=False,
    )
    return created(policy)


@bp.get("/state-policies")
def list_state_policies():
    authorize(ADMIN, CARE_OPS, COMPLIANCE)
    return listed(table_rows(db.state_policies),
                  {"state_code": field("state_code"), "is_retired": field("is_retired")},
                  owner_field=None)


@bp.get("/state-policies/<policy_id>")
def get_state_policy(policy_id):
    authorize(ADMIN, CARE_OPS, COMPLIANCE)
    return ok(svc.find(db.state_policies, policy_id))


@bp.patch("/state-policies/<policy_id>")
def patch_state_policy(policy_id):
    authorize(ADMIN)
    policy = svc.find(db.state_policies, policy_id)
    body = Body()
    if body.present("trial_period_days"):
        policy["trial_period_days"] = body.integer("trial_period_days", minimum=30, maximum=90)
    if body.present("restocking_fee_mode"):
        policy["restocking_fee_mode"] = body.enum("restocking_fee_mode", RESTOCKING_MODES)
    if body.present("restocking_fee_pct"):
        policy["restocking_fee_pct"] = body.number("restocking_fee_pct", minimum=0, maximum=0.20)
    if body.present("restocking_daily_rate_cents"):
        policy["restocking_daily_rate_cents"] = body.integer("restocking_daily_rate_cents",
                                                            minimum=0)
    if body.present("restocking_fee_cap_cents"):
        policy["restocking_fee_cap_cents"] = body.integer("restocking_fee_cap_cents", minimum=0)
    if body.present("shipping_refundable"):
        policy["shipping_refundable"] = body.boolean("shipping_refundable")
    if body.present("waiver_required"):
        policy["waiver_required"] = body.boolean("waiver_required")
    if body.present("otc_sales_permitted"):
        policy["otc_sales_permitted"] = body.boolean("otc_sales_permitted")
    if body.present("telehealth_fitting_permitted"):
        policy["telehealth_fitting_permitted"] = body.boolean("telehealth_fitting_permitted")
    if body.present("min_age_years"):
        policy["min_age_years"] = body.integer("min_age_years", minimum=0, maximum=120)
    if body.present("referral_validity_days"):
        policy["referral_validity_days"] = body.integer("referral_validity_days", minimum=0)
    if body.present("max_loss_damage_claims"):
        policy["max_loss_damage_claims"] = body.integer("max_loss_damage_claims", minimum=0)
    body.finish()
    bump(policy)
    return ok(policy)


@bp.delete("/state-policies/<policy_id>")
def retire_state_policy(policy_id):
    authorize(ADMIN)
    policy = svc.find(db.state_policies, policy_id)
    policy["is_retired"] = True
    bump(policy)
    return ok(policy)


# ------------------------------------------------------------------- Patient
def _new_patient_row(policy, email, full_name, age):
    return svc.new_row(
        db.patients,
        state_policy_id=policy["id"], state_code=policy["state_code"], email=email,
        full_name=full_name, age_years=age, status="REGISTERED",
        waiver_acknowledged_at=None, candidacy_risk_score=0.0,
        candidacy_risk_variant="PROVISIONAL_SELF_REPORTED", candidacy_risk_band="LOW",
        advisory_weight_total=0.0, open_mandatory_flag_count=0, lifetime_return_count=0,
        screening_attempt_count=0, deactivated_at=None,
    )


@bp.post("/patients")
def create_patient():
    authorize(CARE_OPS, ADMIN)
    data = raw_body()
    policy = check_ref("state_policy_id", db.state_policies, data)
    if policy is not None and policy.get("is_retired"):
        raise ApiError("ERR_STATE_POLICY_RETIRED")
    body = Body(data)
    body.string("state_policy_id", min_len=1)
    email = body.string("email", min_len=1)
    full_name = body.string("full_name", min_len=1)
    age = body.integer("age_years", minimum=0, maximum=120)
    body.finish()
    for row in db.patients.values():
        if str(row["email"]).lower() == email.lower():
            raise ApiError("ERR_DUPLICATE_KEY")
    return created(_new_patient_row(policy, email, full_name, age))


@bp.get("/patients")
def list_patients():
    authorize(CARE_OPS, COMPLIANCE, ADMIN, REIMBURSEMENT)
    return listed(table_rows(db.patients),
                  {"state_policy_id": field("state_policy_id"), "status": field("status"),
                   "candidacy_risk_band": field("candidacy_risk_band")},
                  owner_field=None)


@bp.get("/patients/<patient_id>")
def get_patient(patient_id):
    actor = authorize(PATIENT, CARE_OPS, LICENSED_AUDIOLOGIST, HEARING_PROFESSIONAL,
                      COMPLIANCE, REIMBURSEMENT, ADMIN)
    patient = svc.find(db.patients, patient_id)
    require_owner(actor, patient["id"])
    return ok(patient)


@bp.patch("/patients/<patient_id>")
def patch_patient(patient_id):
    actor = authorize(PATIENT, CARE_OPS)
    patient = svc.find(db.patients, patient_id)
    require_owner(actor, patient["id"])
    data = raw_body()
    policy = check_ref("state_policy_id", db.state_policies, data)
    if policy is not None and policy.get("is_retired"):
        raise ApiError("ERR_STATE_POLICY_RETIRED")
    body = Body(data)
    email = body.string("email", required=False, min_len=1)
    full_name = body.string("full_name", required=False, min_len=1)
    age = body.integer("age_years", required=False, minimum=0, maximum=120)
    body.finish()
    if email is not None:
        for row in db.patients.values():
            if row["id"] != patient["id"] and str(row["email"]).lower() == email.lower():
                raise ApiError("ERR_DUPLICATE_KEY")
        patient["email"] = email
    if full_name is not None:
        patient["full_name"] = full_name
    if age is not None:
        patient["age_years"] = age
    if policy is not None:
        patient["state_policy_id"] = policy["id"]
        patient["state_code"] = policy["state_code"]
    bump(patient)
    return ok(patient)


@bp.post("/patients/<patient_id>/acknowledge-waiver")
def acknowledge_waiver(patient_id):
    actor = authorize(PATIENT)
    patient = svc.find(db.patients, patient_id)
    require_owner(actor, patient["id"])
    patient["waiver_acknowledged_at"] = now()
    bump(patient)
    return ok(patient)


@bp.delete("/patients/<patient_id>")
def deactivate_patient(patient_id):
    authorize(ADMIN)
    patient = svc.find(db.patients, patient_id)
    if patient["status"] == "DEACTIVATED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if patient["status"] not in ("REGISTERED", "CANDIDATE_APPROVED", "MEDICALLY_DISQUALIFIED"):
        raise ApiError("ERR_INVALID_STATE")
    for order in db.device_orders.values():
        if order.get("patient_id") != patient["id"]:
            continue
        if order.get("fulfillment_status") not in ("RETURNED", "CANCELLED"):
            raise ApiError("ERR_INVALID_STATE")
    patient["status"] = "DEACTIVATED"
    patient["deactivated_at"] = now()
    bump(patient)
    for session in svc.sessions_of(patient["id"]):
        if session["status"] == "DRAFT":
            session["status"] = "INVALIDATED"
            session["invalidated_reason"] = "DATA_QUALITY"
            bump(session)
    return ok(patient)


# ----------------------------------------------------------- ScreeningSession
@bp.post("/patients/<patient_id>/screening-sessions")
def create_screening(patient_id):
    actor = authorize(PATIENT)
    patient = svc.find(db.patients, patient_id)
    require_owner(actor, patient["id"])
    data = raw_body()
    superseded = check_ref("supersedes_session_id", db.screening_sessions, data)
    Body(data).string("supersedes_session_id", required=False, min_len=1)
    if patient["status"] == "DEACTIVATED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if patient["status"] == "MEDICALLY_DISQUALIFIED":
        raise ApiError("ERR_PATIENT_MEDICALLY_DISQUALIFIED")
    if patient["status"] == "REFERRAL_REQUIRED":
        for referral in table_rows(db.provider_referrals):
            if referral.get("patient_id") != patient["id"]:
                continue
            svc.touch_referral(referral)
            if referral["status"] in ("OPEN", "SCHEDULED", "EVALUATED"):
                raise ApiError("ERR_MANDATORY_REFERRAL_OPEN")
    prior = svc.sessions_of(patient["id"])
    session = svc.new_row(
        db.screening_sessions,
        patient_id=patient["id"],
        supersedes_session_id=superseded["id"] if superseded is not None else None,
        status="DRAFT", attempt_ordinal=len(prior) + 1, pure_tone_avg_db=None,
        asymmetry_db=None, self_reported_difficulty_score=None, speech_in_noise_pct=None,
        symptom_codes=[], screening_outcome="PENDING", submitted_at=None, scored_at=None,
        invalidated_reason=None,
    )
    if patient["status"] in ("REGISTERED", "REFERRAL_REQUIRED"):
        patient["status"] = "SCREENING_IN_PROGRESS"
        bump(patient)
    return created(session)


@bp.get("/patients/<patient_id>/screening-sessions")
def list_patient_screenings(patient_id):
    actor = authorize(PATIENT, CARE_OPS, LICENSED_AUDIOLOGIST, ADMIN)
    patient = svc.find(db.patients, patient_id)
    require_owner(actor, patient["id"])
    rows = svc.sessions_of(patient["id"])
    return listed(rows, {"status": field("status")}, owner_field=None)


@bp.get("/screening-sessions")
def list_screenings():
    actor = authorize(CARE_OPS, LICENSED_AUDIOLOGIST, COMPLIANCE, ADMIN)
    return listed(table_rows(db.screening_sessions),
                  {"patient_id": field("patient_id"),
                   "supersedes_session_id": field("supersedes_session_id"),
                   "status": field("status"),
                   "screening_outcome": field("screening_outcome")},
                  actor=actor)


@bp.get("/screening-sessions/<session_id>")
def get_screening(session_id):
    actor = authorize(PATIENT, CARE_OPS, LICENSED_AUDIOLOGIST, COMPLIANCE, ADMIN)
    session = svc.find(db.screening_sessions, session_id)
    require_owner(actor, session["patient_id"])
    return ok(session)


@bp.patch("/screening-sessions/<session_id>")
def patch_screening(session_id):
    actor = authorize(PATIENT)
    session = svc.find(db.screening_sessions, session_id)
    require_owner(actor, session["patient_id"])
    body = Body()
    ptn = body.number("pure_tone_avg_db", minimum=0, maximum=120)
    asym = body.number("asymmetry_db", minimum=0, maximum=120)
    difficulty = body.integer("self_reported_difficulty_score", minimum=0, maximum=40)
    sin = body.number("speech_in_noise_pct", minimum=0, maximum=100)
    codes = body.array("symptom_codes", required=False, default=None, item_type=str)
    body.finish()
    if session["status"] == "INVALIDATED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if session["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    session["pure_tone_avg_db"] = ptn
    session["asymmetry_db"] = asym
    session["self_reported_difficulty_score"] = difficulty
    session["speech_in_noise_pct"] = sin
    if codes is not None:
        session["symptom_codes"] = list(codes)
    session["status"] = "IN_PROGRESS"
    bump(session)
    return ok(session)


@bp.post("/screening-sessions/<session_id>/submit")
def submit_screening(session_id):
    actor = authorize(PATIENT)
    session = svc.find(db.screening_sessions, session_id)
    require_owner(actor, session["patient_id"])
    patient = db.patients[session["patient_id"]]
    if session["status"] == "INVALIDATED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if session["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE")
    if patient["status"] == "MEDICALLY_DISQUALIFIED":
        raise ApiError("ERR_PATIENT_MEDICALLY_DISQUALIFIED")
    for name in ("pure_tone_avg_db", "asymmetry_db", "self_reported_difficulty_score",
                 "speech_in_noise_pct"):
        if session.get(name) is None:
            raise ApiError("ERR_VALIDATION", "Field '%s' is required" % name)
    policy = svc.policy_of(patient)
    session["submitted_at"] = now()
    session["status"] = "SUBMITTED"
    findings, outcome, advisory_sum = calc.red_flag_referral_trigger(session, patient, policy)
    for finding in findings:
        svc.new_event(db.red_flag_findings, screening_session_id=session["id"],
                      cleared_by_referral_id=None, code=finding["code"],
                      severity=finding["severity"], weight=finding["weight"],
                      detected_at=now())
    session["screening_outcome"] = outcome
    session["scored_at"] = now()
    session["status"] = "SCORED"
    bump(session)
    if session.get("supersedes_session_id"):
        prior = db.screening_sessions.get(session["supersedes_session_id"])
        if prior is not None and prior["status"] not in ("INVALIDATED",):
            prior["status"] = "INVALIDATED"
            prior["invalidated_reason"] = "SUPERSEDED"
            bump(prior)
    svc.recompute_screening_attempt_count(patient)
    svc.recompute_patient_counters(patient)
    if outcome in ("PASS", "ADVISORY_PASS"):
        score = calc.candidacy_risk_score(session, "PROVISIONAL_SELF_REPORTED")
        patient["candidacy_risk_score"] = score
        patient["candidacy_risk_variant"] = "PROVISIONAL_SELF_REPORTED"
        patient["candidacy_risk_band"] = calc.risk_band(score)
        patient["status"] = "CANDIDATE_APPROVED"
        bump(patient)
    else:
        patient["status"] = "REFERRAL_REQUIRED"
        bump(patient)
        validity = 180 if policy is None else int(policy.get("referral_validity_days") or 180)
        svc.new_row(db.provider_referrals, patient_id=patient["id"],
                    triggering_screening_session_id=session["id"], provider_id=None,
                    status="OPEN", reason_codes=[f["code"] for f in findings],
                    issued_at=now(), expires_at=now() + days(validity), reschedule_count=0,
                    clearance_outcome="PENDING", clearance_note=None,
                    cleared_finding_count=0,
                    _advisory_at_issue=patient.get("advisory_weight_total") or 0.0)
        svc.cascade_medical_hold(patient)
    return ok(session)


@bp.post("/screening-sessions/<session_id>/invalidate")
def invalidate_screening(session_id):
    actor = authorize(LICENSED_AUDIOLOGIST)
    session = svc.find(db.screening_sessions, session_id)
    require_audiologist(actor)
    Body().string("reason_note", required=False, min_len=1)
    patient = db.patients.get(session["patient_id"])
    provider = actor.provider
    if provider.get("status") != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    if patient is not None and patient.get("state_code") not in (
            provider.get("licensed_state_codes") or []):
        raise ApiError("ERR_PROVIDER_NOT_LICENSED_IN_STATE")
    if session["status"] == "INVALIDATED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if session["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE")
    session["status"] = "INVALIDATED"
    session["invalidated_reason"] = "DATA_QUALITY"
    session["_invalidated_by_provider_id"] = actor.user_id
    bump(session)
    if patient is not None:
        svc.recompute_patient_counters(patient)
        svc.recompute_screening_attempt_count(patient)
        bump(patient)
    return ok(session)


# --------------------------------------------------------------- findings
@bp.get("/screening-sessions/<session_id>/red-flag-findings")
def list_session_findings(session_id):
    actor = authorize(PATIENT, LICENSED_AUDIOLOGIST, CARE_OPS, COMPLIANCE, ADMIN)
    session = svc.find(db.screening_sessions, session_id)
    require_owner(actor, session["patient_id"])
    rows = svc.findings_of_session(session["id"])
    return listed(rows, {"severity": field("severity")}, owner_field=None)


@bp.get("/red-flag-findings")
def list_findings():
    authorize(LICENSED_AUDIOLOGIST, CARE_OPS, COMPLIANCE, ADMIN)
    return listed(table_rows(db.red_flag_findings),
                  {"screening_session_id": field("screening_session_id"),
                   "cleared_by_referral_id": field("cleared_by_referral_id"),
                   "code": field("code"), "severity": field("severity")},
                  owner_field=None)


# ------------------------------------------------------- ComplianceOverride
@bp.post("/patients/<patient_id>/compliance-overrides")
def file_override(patient_id):
    actor = authorize(COMPLIANCE)
    patient = svc.find(db.patients, patient_id)
    body = Body()
    justification = body.string("justification", min_len=20, max_len=2000)
    body.finish()
    if patient["status"] != "MEDICALLY_DISQUALIFIED":
        raise ApiError("ERR_INVALID_STATE")
    override = svc.new_row(db.compliance_overrides, patient_id=patient["id"],
                           filed_by_user_id=actor.user_id, approved_by_user_id=None,
                           justification=justification, status="PENDING", filed_at=now(),
                           decided_at=None)
    return created(override)


@bp.get("/patients/<patient_id>/compliance-overrides")
def list_overrides(patient_id):
    authorize(COMPLIANCE, ADMIN)
    patient = svc.find(db.patients, patient_id)
    rows = [o for o in table_rows(db.compliance_overrides)
            if o["patient_id"] == patient["id"]]
    return listed(rows, {"status": field("status")}, owner_field=None)


def _load_override(patient_id, override_id):
    patient = svc.find(db.patients, patient_id)
    override = svc.find(db.compliance_overrides, override_id)
    if override["patient_id"] != patient["id"]:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    return patient, override


@bp.post("/patients/<patient_id>/compliance-overrides/<override_id>/approve")
def approve_override(patient_id, override_id):
    actor = authorize(COMPLIANCE)
    patient, override = _load_override(patient_id, override_id)
    require_distinct_user(actor, override.get("filed_by_user_id"))
    if override["status"] in ("APPROVED", "REJECTED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if patient["status"] != "MEDICALLY_DISQUALIFIED":
        raise ApiError("ERR_INVALID_STATE")
    override["status"] = "APPROVED"
    override["approved_by_user_id"] = actor.user_id
    override["decided_at"] = now()
    bump(override)
    latest = calc.latest_scored_session(patient["id"])
    if latest is not None:
        latest["status"] = "INVALIDATED"
        latest["invalidated_reason"] = "PROVIDER_OVERRIDE"
        bump(latest)
    patient["status"] = "SCREENING_IN_PROGRESS"
    patient["open_mandatory_flag_count"] = 0
    patient["advisory_weight_total"] = 0.0
    svc.recompute_screening_attempt_count(patient)
    bump(patient)
    svc.new_row(db.screening_sessions, patient_id=patient["id"], supersedes_session_id=None,
                status="DRAFT", attempt_ordinal=int(patient["screening_attempt_count"]) + 1,
                pure_tone_avg_db=None, asymmetry_db=None,
                self_reported_difficulty_score=None, speech_in_noise_pct=None,
                symptom_codes=[], screening_outcome="PENDING", submitted_at=None,
                scored_at=None, invalidated_reason=None)
    return ok(override)


@bp.post("/patients/<patient_id>/compliance-overrides/<override_id>/reject")
def reject_override(patient_id, override_id):
    actor = authorize(COMPLIANCE)
    patient, override = _load_override(patient_id, override_id)
    require_distinct_user(actor, override.get("filed_by_user_id"))
    Body().string("reason_note", required=False, min_len=1)
    if override["status"] in ("APPROVED", "REJECTED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    override["status"] = "REJECTED"
    override["decided_at"] = now()
    bump(override)
    return ok(override)
