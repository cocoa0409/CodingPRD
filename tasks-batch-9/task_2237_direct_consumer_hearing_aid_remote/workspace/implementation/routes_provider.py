"""Providers, provider referrals and remote fitting sessions."""

from flask import Blueprint

import calc
import services as svc
from auth import (ADMIN, CARE_OPS, COMPLIANCE, HEARING_PROFESSIONAL, LICENSED_AUDIOLOGIST,
                  PATIENT, authorize, require_assigned_provider, require_audiologist,
                  require_no_conflict, require_owner)
from bodyspec import Body, raw_body
from common import field, listed
from errors import ApiError
from resp import created, ok
from routes_policy import check_ref
from store import bump, db, minutes, now, table_rows

bp = Blueprint("provider", __name__)

PROVIDER_TYPES = ("TELECARE_FITTER", "LICENSED_AUDIOLOGIST")
PROVIDER_STATUSES = ("ACTIVE", "SUSPENDED", "OFFBOARDED")
SESSION_TYPES = ("INITIAL_FIT", "FOLLOW_UP", "REFERRAL_EVALUATION", "TROUBLESHOOT")
CLEARANCE_OUTCOMES = ("CLEARED", "NOT_CLEARED")


# ------------------------------------------------------------------ Provider
@bp.post("/providers")
def create_provider():
    authorize(ADMIN)
    body = Body()
    provider_type = body.enum("provider_type", PROVIDER_TYPES)
    npi = body.string("npi", min_len=10, max_len=10)
    full_name = body.string("full_name", min_len=1)
    states = body.array("licensed_state_codes", item_type=str)
    capacity = body.integer("daily_capacity_minutes", minimum=1, maximum=600)
    buffer_minutes = body.integer("buffer_minutes", required=False, default=10, minimum=0,
                                  maximum=60)
    body.finish()
    if not npi.isdigit():
        raise ApiError("ERR_VALIDATION", "npi must be 10 digits")
    if not states:
        raise ApiError("ERR_VALIDATION", "licensed_state_codes must not be empty")
    for code in states:
        if len(code) != 2 or code != code.upper():
            raise ApiError("ERR_VALIDATION", "licensed_state_codes entries must be 2 uppercase")
    for row in db.providers.values():
        if row["npi"] == npi:
            raise ApiError("ERR_DUPLICATE_KEY")
    provider = svc.new_row(db.providers, provider_type=provider_type, npi=npi,
                           full_name=full_name, licensed_state_codes=list(states),
                           status="ACTIVE", daily_capacity_minutes=capacity,
                           buffer_minutes=buffer_minutes, booked_minutes_on_focus_date=0,
                           utilization_pct=0.0, completed_session_count=0)
    return created(provider)


@bp.get("/providers")
def list_providers():
    authorize(PATIENT, CARE_OPS, HEARING_PROFESSIONAL, LICENSED_AUDIOLOGIST, ADMIN)
    return listed(table_rows(db.providers),
                  {"provider_type": field("provider_type"), "status": field("status"),
                   "licensed_state_code": field("licensed_state_codes")},
                  owner_field=None)


@bp.get("/providers/<provider_id>")
def get_provider(provider_id):
    authorize(PATIENT, CARE_OPS, HEARING_PROFESSIONAL, LICENSED_AUDIOLOGIST, ADMIN)
    return ok(svc.find(db.providers, provider_id))


@bp.patch("/providers/<provider_id>")
def patch_provider(provider_id):
    authorize(ADMIN)
    provider = svc.find(db.providers, provider_id)
    body = Body()
    status = body.enum("status", PROVIDER_STATUSES, required=False)
    capacity = body.integer("daily_capacity_minutes", required=False, minimum=1, maximum=600)
    buffer_minutes = body.integer("buffer_minutes", required=False, minimum=0, maximum=60)
    states = body.array("licensed_state_codes", required=False, item_type=str)
    body.finish()
    if status is not None:
        provider["status"] = status
    if capacity is not None:
        provider["daily_capacity_minutes"] = capacity
        provider["utilization_pct"] = calc.utilization(
            provider["booked_minutes_on_focus_date"], capacity)
    if buffer_minutes is not None:
        provider["buffer_minutes"] = buffer_minutes
    if states is not None:
        if not states:
            raise ApiError("ERR_VALIDATION", "licensed_state_codes must not be empty")
        provider["licensed_state_codes"] = list(states)
    bump(provider)
    return ok(provider)


# ----------------------------------------------------------- ProviderReferral
@bp.get("/provider-referrals")
def list_referrals():
    actor = authorize(PATIENT, LICENSED_AUDIOLOGIST, CARE_OPS, COMPLIANCE, ADMIN)
    svc.touch_all_referrals()
    return listed(table_rows(db.provider_referrals),
                  {"patient_id": field("patient_id"), "provider_id": field("provider_id"),
                   "triggering_screening_session_id":
                       field("triggering_screening_session_id"),
                   "status": field("status")},
                  actor=actor)


@bp.get("/provider-referrals/<referral_id>")
def get_referral(referral_id):
    actor = authorize(PATIENT, LICENSED_AUDIOLOGIST, CARE_OPS, COMPLIANCE, ADMIN)
    referral = svc.find(db.provider_referrals, referral_id)
    require_owner(actor, referral["patient_id"])
    svc.touch_referral(referral)
    return ok(referral)


@bp.get("/provider-referrals/<referral_id>/cleared-findings")
def list_cleared_findings(referral_id):
    authorize(LICENSED_AUDIOLOGIST, CARE_OPS, COMPLIANCE, ADMIN)
    referral = svc.find(db.provider_referrals, referral_id)
    rows = [f for f in table_rows(db.red_flag_findings)
            if f.get("cleared_by_referral_id") == referral["id"]]
    return listed(rows, None, owner_field=None)


@bp.post("/provider-referrals/<referral_id>/determination")
def referral_determination(referral_id):
    actor = authorize(LICENSED_AUDIOLOGIST)
    referral = svc.find(db.provider_referrals, referral_id)
    require_assigned_provider(actor, referral.get("provider_id"))
    require_audiologist(actor)
    require_no_conflict(actor.user_id, referral.get("triggering_screening_session_id"))
    body = Body()
    outcome = body.enum("clearance_outcome", CLEARANCE_OUTCOMES)
    note = body.string("clearance_note", required=False, min_len=1)
    body.finish()
    patient = db.patients.get(referral["patient_id"])
    provider = actor.provider
    if patient is not None and patient.get("state_code") not in (
            provider.get("licensed_state_codes") or []):
        raise ApiError("ERR_PROVIDER_NOT_LICENSED_IN_STATE")
    svc.touch_referral(referral)
    svc.ensure_state(referral, "status", ("EVALUATED",), "provider_referrals")
    if now() >= referral["expires_at"]:
        raise ApiError("ERR_REFERRAL_EXPIRED")
    referral["clearance_note"] = note
    if outcome == "CLEARED":
        codes = set(referral.get("reason_codes") or [])
        cleared = 0
        cleared_mandatory = 0
        live_ids = set(s["id"] for s in svc.sessions_of(patient["id"])
                       if s.get("status") != "INVALIDATED")
        for finding in table_rows(db.red_flag_findings):
            if finding.get("screening_session_id") not in live_ids:
                continue
            if finding.get("cleared_by_referral_id") is not None:
                continue
            if finding.get("code") not in codes:
                continue
            finding["cleared_by_referral_id"] = referral["id"]
            cleared += 1
            if finding.get("severity") == "MANDATORY_REFERRAL":
                cleared_mandatory += 1
        referral["cleared_finding_count"] = cleared
        referral["status"] = "CLEARED"
        referral["clearance_outcome"] = "CLEARED"
        bump(referral)
        advisory_at_issue = referral.get("_advisory_at_issue")
        if advisory_at_issue is None:
            advisory_at_issue = patient.get("advisory_weight_total") or 0.0
        svc.recompute_patient_counters(patient)
        session = db.screening_sessions.get(referral.get("triggering_screening_session_id"))
        if session is None or session.get("status") == "INVALIDATED":
            session = calc.latest_scored_session(patient["id"])
        score = calc.candidacy_risk_score(session, "PROVIDER_ADJUSTED",
                                          cleared_mandatory=cleared_mandatory,
                                          advisory_weight_total=advisory_at_issue)
        patient["candidacy_risk_score"] = score
        patient["candidacy_risk_variant"] = "PROVIDER_ADJUSTED"
        patient["candidacy_risk_band"] = calc.risk_band(score)
        patient["status"] = "PROVIDER_CLEARED"
        bump(patient)
        svc.release_medical_hold(patient)
    else:
        referral["status"] = "NOT_CLEARED"
        referral["clearance_outcome"] = "NOT_CLEARED"
        bump(referral)
        patient["status"] = "MEDICALLY_DISQUALIFIED"
        bump(patient)
        svc.cancel_held_orders(patient)
    return ok(referral)


@bp.post("/provider-referrals/<referral_id>/withdraw")
def withdraw_referral(referral_id):
    authorize(COMPLIANCE)
    referral = svc.find(db.provider_referrals, referral_id)
    Body().string("reason_note", required=False, min_len=1)
    svc.touch_referral(referral)
    svc.ensure_state(referral, "status", ("OPEN",), "provider_referrals")
    for session in db.remote_fitting_sessions.values():
        if session.get("provider_referral_id") == referral["id"] and \
                session.get("status") in ("SCHEDULED", "IN_PROGRESS"):
            raise ApiError("ERR_INVALID_STATE")
    referral["status"] = "WITHDRAWN"
    bump(referral)
    return ok(referral)


# ------------------------------------------------------- RemoteFittingSession
def _plan_with_fee(patient_id):
    for plan in table_rows(db.care_plan_subscriptions):
        if plan.get("patient_id") == patient_id and plan.get("status") in ("ACTIVE", "PAST_DUE"):
            return plan
    return None


@bp.post("/remote-fitting-sessions")
def create_fitting_session():
    actor = authorize(PATIENT)
    data = raw_body()
    patient = check_ref("patient_id", db.patients, data)
    provider = check_ref("provider_id", db.providers, data)
    order = check_ref("device_order_id", db.device_orders, data)
    referral = check_ref("provider_referral_id", db.provider_referrals, data)
    body = Body(data)
    body.string("patient_id", min_len=1)
    session_type = body.enum("session_type", SESSION_TYPES)
    start = body.datetime("scheduled_start_utc")
    end = body.datetime("scheduled_end_utc")
    profile = body.string("programming_profile", required=False, min_len=1)
    body.finish()
    require_owner(actor, patient["id"])
    if end <= start:
        raise ApiError("ERR_VALIDATION", "scheduled_end_utc must follow scheduled_start_utc")
    duration = int((end - start).total_seconds() // 60)
    if duration < 15 or duration > 120:
        raise ApiError("ERR_VALIDATION", "duration_minutes must be between 15 and 120")
    if patient["status"] == "MEDICALLY_DISQUALIFIED":
        raise ApiError("ERR_PATIENT_MEDICALLY_DISQUALIFIED")
    policy = svc.policy_of(patient)

    if session_type == "REFERRAL_EVALUATION":
        if referral is None:
            raise ApiError("ERR_VALIDATION", "provider_referral_id is required")
        svc.touch_referral(referral)
        if referral["status"] not in ("OPEN",):
            if referral["status"] in ("CLEARED", "NOT_CLEARED", "EXPIRED", "WITHDRAWN"):
                if referral["status"] == "EXPIRED":
                    raise ApiError("ERR_REFERRAL_EXPIRED")
                raise ApiError("ERR_ALREADY_TERMINAL")
            raise ApiError("ERR_INVALID_STATE")
        if now() >= referral["expires_at"]:
            raise ApiError("ERR_REFERRAL_EXPIRED")
        if int(referral.get("reschedule_count") or 0) >= 2:
            raise ApiError("ERR_MAX_RESCHEDULES_EXCEEDED")
        if provider is None:
            provider = calc.select_referral_provider(patient, referral, start, end, duration)
        else:
            require_no_conflict(provider["id"],
                                referral.get("triggering_screening_session_id"))
            if provider.get("provider_type") != "LICENSED_AUDIOLOGIST":
                raise ApiError("ERR_PROVIDER_TYPE_NOT_PERMITTED")
            if patient.get("state_code") not in (provider.get("licensed_state_codes") or []):
                raise ApiError("ERR_PROVIDER_NOT_LICENSED_IN_STATE")
    if provider is None:
        raise ApiError("ERR_VALIDATION", "provider_id is required")
    if provider.get("status") != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    if policy is not None and not policy.get("telehealth_fitting_permitted"):
        if patient.get("state_code") not in (provider.get("licensed_state_codes") or []):
            raise ApiError("ERR_TELEHEALTH_NOT_PERMITTED_IN_STATE")
    if calc.slot_conflict(provider, start, end):
        raise ApiError("ERR_PROVIDER_SLOT_CONFLICT")
    accepts, booked = calc.capacity_accepts(provider, start.date(), duration)
    if not accepts:
        raise ApiError("ERR_PROVIDER_CAPACITY_EXCEEDED")

    session = svc.new_row(db.remote_fitting_sessions, patient_id=patient["id"],
                          provider_id=provider["id"],
                          device_order_id=order["id"] if order is not None else None,
                          provider_referral_id=referral["id"] if referral is not None else None,
                          session_type=session_type, status="SCHEDULED",
                          scheduled_start_utc=start, scheduled_end_utc=end,
                          duration_minutes=duration, programming_profile=profile,
                          no_show_charged_cents=0, completed_at=None)
    svc.refresh_provider_counters(provider, start.date())
    if session_type == "REFERRAL_EVALUATION":
        referral["status"] = "SCHEDULED"
        referral["provider_id"] = provider["id"]
        bump(referral)
    return created(session)


@bp.get("/remote-fitting-sessions")
def list_fitting_sessions():
    actor = authorize(PATIENT, HEARING_PROFESSIONAL, LICENSED_AUDIOLOGIST, CARE_OPS, ADMIN)
    return listed(table_rows(db.remote_fitting_sessions),
                  {"patient_id": field("patient_id"), "provider_id": field("provider_id"),
                   "device_order_id": field("device_order_id"),
                   "provider_referral_id": field("provider_referral_id"),
                   "status": field("status"), "session_type": field("session_type")},
                  actor=actor)


@bp.get("/remote-fitting-sessions/<session_id>")
def get_fitting_session(session_id):
    actor = authorize(PATIENT, HEARING_PROFESSIONAL, LICENSED_AUDIOLOGIST, CARE_OPS, ADMIN)
    session = svc.find(db.remote_fitting_sessions, session_id)
    require_owner(actor, session["patient_id"])
    return ok(session)


@bp.post("/remote-fitting-sessions/<session_id>/start")
def start_fitting_session(session_id):
    actor = authorize(HEARING_PROFESSIONAL, LICENSED_AUDIOLOGIST)
    session = svc.find(db.remote_fitting_sessions, session_id)
    require_assigned_provider(actor, session.get("provider_id"))
    svc.ensure_state(session, "status", ("SCHEDULED",), "remote_fitting_sessions")
    if session["session_type"] == "INITIAL_FIT":
        order = db.device_orders.get(session.get("device_order_id"))
        if order is None or order.get("fulfillment_status") != "DELIVERED":
            raise ApiError("ERR_DEPENDENT_STATE_NOT_READY")
    if not (session["scheduled_start_utc"] <= now() < session["scheduled_end_utc"]):
        raise ApiError("ERR_SESSION_WINDOW_NOT_OPEN")
    session["status"] = "IN_PROGRESS"
    bump(session)
    return ok(session)


@bp.post("/remote-fitting-sessions/<session_id>/complete")
def complete_fitting_session(session_id):
    actor = authorize(HEARING_PROFESSIONAL, LICENSED_AUDIOLOGIST)
    session = svc.find(db.remote_fitting_sessions, session_id)
    require_assigned_provider(actor, session.get("provider_id"))
    body = Body()
    profile = body.string("programming_profile", required=False, min_len=1)
    body.finish()
    svc.ensure_state(session, "status", ("IN_PROGRESS",), "remote_fitting_sessions")
    if profile is not None:
        session["programming_profile"] = profile
    if session["session_type"] in ("INITIAL_FIT", "FOLLOW_UP", "TROUBLESHOOT") and \
            not session.get("programming_profile"):
        raise ApiError("ERR_VALIDATION", "programming_profile is required")
    referral = db.provider_referrals.get(session.get("provider_referral_id"))
    if session["session_type"] == "REFERRAL_EVALUATION" and referral is not None:
        svc.touch_referral(referral)
        if referral["status"] == "EXPIRED" or now() >= referral["expires_at"]:
            raise ApiError("ERR_REFERRAL_EXPIRED")
    session["status"] = "COMPLETED"
    session["completed_at"] = now()
    bump(session)
    provider = db.providers.get(session["provider_id"])
    if provider is not None:
        provider["completed_session_count"] = int(
            provider.get("completed_session_count") or 0) + 1
        bump(provider)
    if session["session_type"] == "INITIAL_FIT":
        order = db.device_orders.get(session.get("device_order_id"))
        if order is not None:
            device = svc.device_for_order(order["id"])
            if device is not None and device.get("status") != "WITH_PATIENT":
                device["status"] = "WITH_PATIENT"
                bump(device)
    if session["session_type"] == "REFERRAL_EVALUATION" and referral is not None:
        if referral["status"] == "SCHEDULED":
            referral["status"] = "EVALUATED"
            referral["clearance_outcome"] = "PENDING"
            bump(referral)
    return ok(session)


def _release_referral(session, increment=True):
    referral = db.provider_referrals.get(session.get("provider_referral_id"))
    if referral is None or session["session_type"] != "REFERRAL_EVALUATION":
        return
    if referral["status"] != "SCHEDULED":
        return
    referral["status"] = "OPEN"
    referral["provider_id"] = None
    if increment:
        referral["reschedule_count"] = int(referral.get("reschedule_count") or 0) + 1
    bump(referral)


@bp.post("/remote-fitting-sessions/<session_id>/no-show")
def no_show_fitting_session(session_id):
    actor = authorize(HEARING_PROFESSIONAL, LICENSED_AUDIOLOGIST)
    session = svc.find(db.remote_fitting_sessions, session_id)
    require_assigned_provider(actor, session.get("provider_id"))
    svc.ensure_state(session, "status", ("SCHEDULED",), "remote_fitting_sessions")
    if now() < session["scheduled_end_utc"]:
        raise ApiError("ERR_SESSION_WINDOW_NOT_OPEN")
    plan = _plan_with_fee(session["patient_id"])
    fee = calc.NO_SHOW_FEE_CENTS if plan is not None else 0
    session["no_show_charged_cents"] = fee
    session["status"] = "NO_SHOW"
    bump(session)
    if fee:
        svc.charge_plan(plan, fee)
    provider = db.providers.get(session["provider_id"])
    if provider is not None:
        svc.refresh_provider_counters(provider, session["scheduled_start_utc"].date())
    _release_referral(session)
    return ok(session)


@bp.post("/remote-fitting-sessions/<session_id>/cancel")
def cancel_fitting_session(session_id):
    actor = authorize(PATIENT, CARE_OPS)
    session = svc.find(db.remote_fitting_sessions, session_id)
    require_owner(actor, session["patient_id"])
    svc.ensure_state(session, "status", ("SCHEDULED", "REQUESTED"), "remote_fitting_sessions")
    if session["status"] == "REQUESTED":
        session["status"] = "CANCELLED"
        session["no_show_charged_cents"] = 0
        bump(session)
        return ok(session)
    start = session["scheduled_start_utc"]
    if now() >= start:
        raise ApiError("ERR_SESSION_WINDOW_NOT_OPEN")
    plan = _plan_with_fee(session["patient_id"])
    fee = 0
    if plan is not None and (start - now()) <= minutes(24 * 60):
        fee = calc.LATE_CANCEL_FEE_CENTS
    session["no_show_charged_cents"] = fee
    session["status"] = "CANCELLED"
    bump(session)
    if fee:
        svc.charge_plan(plan, fee)
    provider = db.providers.get(session["provider_id"])
    if provider is not None:
        svc.refresh_provider_counters(provider, start.date())
    _release_referral(session)
    return ok(session)


@bp.post("/remote-fitting-sessions/<session_id>/rebook")
def rebook_fitting_session(session_id):
    actor = authorize(PATIENT)
    session = svc.find(db.remote_fitting_sessions, session_id)
    require_owner(actor, session["patient_id"])
    svc.ensure_state(session, "status", ("NO_SHOW",), "remote_fitting_sessions")
    patient = db.patients.get(session["patient_id"])
    if patient is not None and patient["status"] in ("MEDICALLY_DISQUALIFIED", "DEACTIVATED"):
        raise ApiError("ERR_PATIENT_MEDICALLY_DISQUALIFIED")
    provider = db.providers.get(session["provider_id"])
    focus = session.get("scheduled_start_utc")
    session["status"] = "REQUESTED"
    session["scheduled_start_utc"] = None
    session["scheduled_end_utc"] = None
    bump(session)
    if provider is not None and focus is not None:
        svc.refresh_provider_counters(provider, focus.date())
    return ok(session)
