"""Verification sessions, the age axis, inclusion pathway requests and session reads."""
import re
from datetime import datetime

from flask import Blueprint

import auth
import calc
import clock
import db
import derived
import response
import schema
import services
import views
from errors import fail
from schema import Field
from . import support

bp = Blueprint("sessions", __name__)

TIERS = ("BASIC", "STANDARD", "ENHANCED")
DOCUMENTATION_STATUSES = ("STANDARD_DOCS", "NO_STANDARD_DOCS")
IDENTITY_STATES = ("IN_PROGRESS", "AWAITING_EVIDENCE", "MANUAL_REVIEW", "VERIFIED", "REJECTED", "EXPIRED")
AGE_STATES = ("NOT_REQUIRED", "PENDING", "ASSURED", "FAILED")
PATHWAY_STATES = ("VOUCH_PENDING", "ATTESTATION_PENDING", "APPROVED", "DENIED", "WITHDRAWN")
TEMPLATE_STATES = ("STORED", "PURGE_SCHEDULED", "DELETED")
REVIEW_CASE_STATES = ("QUEUED", "ASSIGNED", "DECIDED", "WITHDRAWN")
EVENT_TYPES = ("SESSION_CREATED", "ATTEMPT_FINALIZED", "STEP_UP_TRIGGERED", "ESCALATED_TO_REVIEW",
               "REVIEW_DECIDED", "PATHWAY_DECIDED", "METHOD_RESTRICTION_APPLIED",
               "TEMPLATE_DELETED", "SESSION_TERMINAL")
NON_ATTEMPTABLE_METHODS = ("VOUCHING_ATTESTATION", "AGE_ESTIMATION")

SESSION_FIELDS = (
    Field("client_id", "string", required=True),
    Field("external_subject_ref", "string", required=True, min_len=1, max_len=64),
    Field("requested_assurance_tier", "string", required=True, enum=TIERS),
    Field("subject_jurisdiction_code", "string", required=True, regex=r"[A-Z]{2}"),
    Field("declared_transaction_value_cents", "int", default=0, minimum=0),
    Field("biometric_consent", "bool", default=False),
    Field("documentation_status", "string", default="STANDARD_DOCS", enum=DOCUMENTATION_STATUSES),
)

ATTEMPT_FIELDS = (
    Field("method_profile_id", "string", default=None),
)

AGE_RESULT_FIELDS = (
    Field("method", "string", required=True, enum=("ESTIMATION", "VERIFICATION")),
    Field("estimation_profile_id", "string", default=None),
    Field("estimated_age_months", "int", default=None, minimum=0, maximum=1200),
    Field("date_of_birth", "string", default=None),
)

PATHWAY_FIELDS = (
    Field("pathway_type", "string", required=True, enum=("VOUCHING", "ATTESTATION")),
    Field("voucher_reference", "string", default=None, min_len=1, max_len=120),
    Field("attestation_document_ref", "string", default=None, min_len=1, max_len=120),
)


def _session_or_404(session_id):
    session = db.get(db.SESSIONS, session_id)
    if session is None:
        fail("ERR_SESSION_NOT_FOUND")
    return session


def _guard(session_id, caller):
    session = _session_or_404(session_id)
    auth.require_own_client(caller, session["client_id"])
    return session


# --- creation and reads -----------------------------------------------------

@bp.post("/idv/verification-sessions")
def create_session():
    caller = auth.authenticate((auth.CLIENT_INTEGRATOR,))
    support.scope_check_body_client(caller)
    values = schema.validate(schema.read_body(), SESSION_FIELDS)
    client = db.get(db.CLIENTS, values["client_id"])
    if client is None:
        fail("ERR_CLIENT_NOT_FOUND")
    if client["integration_state"] != "LIVE":
        fail("ERR_CLIENT_NOT_LIVE")
    policy = services.pin_policy(client["id"])
    if policy is None:
        fail("ERR_NO_PUBLISHED_POLICY")
    if services.rolling_window_usage(client["id"]) >= client["daily_session_quota"]:
        fail("ERR_CLIENT_DAILY_QUOTA_EXCEEDED")

    prior_rejects = services.prior_rejected_count(client["id"], values["external_subject_ref"])
    risk_score, risk_level = calc.session_risk(
        values["requested_assurance_tier"],
        values["declared_transaction_value_cents"],
        values["subject_jurisdiction_code"],
        client["home_jurisdiction_code"],
        values["documentation_status"],
        prior_rejects,
    )
    record = {
        "client_id": client["id"],
        "policy_id": policy["id"],
        "external_subject_ref": values["external_subject_ref"],
        "requested_assurance_tier": values["requested_assurance_tier"],
        "declared_transaction_value_cents": values["declared_transaction_value_cents"],
        "subject_jurisdiction_code": values["subject_jurisdiction_code"],
        "biometric_consent": values["biometric_consent"],
        "documentation_status": values["documentation_status"],
        "risk_score": risk_score,
        "risk_level": risk_level,
        "identity_state": "IN_PROGRESS",
        "age_state": "NOT_REQUIRED" if policy["required_min_age_years"] == 0 else "PENDING",
        "assurance_score_provisional": 0,
        "assurance_score_final": None,
        "assurance_ceiling": calc.SCORE_CAP,
        "resolved_age_band": None,
        "step_up_round": 0,
        "manual_override_flag": False,
        "disposition_reason": None,
        "completed_at": None,
    }
    db.insert(db.SESSIONS, record)
    record["expires_at"] = clock.plus_minutes(record["created_at"], calc.SESSION_TTL_MINUTES)
    services.append_event(record, "SESSION_CREATED", caller,
                          "identity_state, age_state, policy_id, risk_score, risk_level, expires_at")
    return response.object_response(views.session_view(record), 201)


@bp.get("/idv/verification-sessions/<session_id>")
def read_session(session_id):
    caller = auth.authenticate(auth.ROLES)
    session = _guard(session_id, caller)
    return response.object_response(views.session_view(session))


@bp.get("/idv/verification-sessions")
def list_sessions():
    caller = auth.authenticate((auth.PLATFORM_ADMIN, auth.COMPLIANCE_OFFICER, auth.CLIENT_INTEGRATOR))
    client_id = support.string_filter("client_id")
    if caller.is_client_integrator:
        if client_id is not None and client_id != caller.user_id:
            fail("ERR_CLIENT_SCOPE_VIOLATION")
        client_id = caller.user_id
    policy_id = support.string_filter("policy_id")
    identity_state = support.enum_filter("identity_state", IDENTITY_STATES)
    age_state = support.enum_filter("age_state", AGE_STATES)
    subject_ref = support.string_filter("external_subject_ref")
    records = db.all_of(db.SESSIONS)
    if client_id is not None:
        records = [s for s in records if s["client_id"] == client_id]
    if policy_id is not None:
        records = [s for s in records if s["policy_id"] == policy_id]
    if identity_state is not None:
        records = [s for s in records if s["identity_state"] == identity_state]
    if age_state is not None:
        records = [s for s in records if s["age_state"] == age_state]
    if subject_ref is not None:
        records = [s for s in records if s["external_subject_ref"] == subject_ref]
    page, limit, offset, total = support.paginated(records)
    return response.list_response([views.session_view(s) for s in page], limit, offset, total)


# --- method attempts --------------------------------------------------------

@bp.post("/idv/verification-sessions/<session_id>/method-attempts")
def create_method_attempt(session_id):
    caller = auth.authenticate((auth.CLIENT_INTEGRATOR,))
    session = _guard(session_id, caller)
    values = schema.validate(schema.read_body() if schema.body_or_none() is not None else {},
                             ATTEMPT_FIELDS)
    requested_id = values.get("method_profile_id")
    requested = None
    if requested_id is not None:
        requested = db.get(db.METHOD_PROFILES, requested_id)
        if requested is None:
            fail("ERR_METHOD_PROFILE_NOT_FOUND")
    if session["identity_state"] != "IN_PROGRESS":
        fail("ERR_SESSION_STATE_INVALID")
    client = services.client_of_session(session)
    if client is None or client["integration_state"] == "SUSPENDED":
        fail("ERR_CLIENT_NOT_LIVE")
    policy = services.policy_of_session(session)
    if policy is None or policy["state"] != "PUBLISHED":
        fail("ERR_PINNED_POLICY_RETIRED")
    if requested is not None:
        if requested["bias_state"] == "RESTRICTED":
            fail("ERR_METHOD_RESTRICTED_BY_BIAS")
        if requested["method_code"] in NON_ATTEMPTABLE_METHODS:
            fail("ERR_METHOD_NOT_DIRECTLY_ATTEMPTABLE")
        if requested["method_code"] not in policy["allowed_method_codes"]:
            fail("ERR_METHOD_NOT_IN_POLICY")
    services.require_not_lapsed(session)

    if requested is not None:
        profile = requested
        selection_mode = "CLIENT_REQUESTED"
    else:
        profile = services.select_ladder_profile(session, policy)
        if profile is None:
            fail("ERR_NO_ELIGIBLE_METHOD")
        selection_mode = "SERVER_SELECTED"
    attempt = services.create_attempt(session, profile, selection_mode)
    return response.object_response(views.attempt_view(attempt), 201)


# --- age assurance ----------------------------------------------------------

def _months_from_dob(text):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text or ""):
        fail("ERR_INVALID_REQUEST", "date_of_birth must be an ISO date in YYYY-MM-DD form.")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        fail("ERR_INVALID_REQUEST", "date_of_birth is not a valid calendar date.")
    return calc.complete_months_between(parsed.year, parsed.month, parsed.day, clock.now())


@bp.post("/idv/verification-sessions/<session_id>/age-assurance-results")
def create_age_result(session_id):
    caller = auth.authenticate((auth.CLIENT_INTEGRATOR,))
    session = _guard(session_id, caller)
    values = schema.validate(schema.read_body(), AGE_RESULT_FIELDS)
    method = values["method"]
    if method == "ESTIMATION":
        if values["estimated_age_months"] is None or values["estimation_profile_id"] is None:
            fail("ERR_INVALID_REQUEST",
                 "An ESTIMATION result requires estimated_age_months and estimation_profile_id.")
        if values["date_of_birth"] is not None:
            fail("ERR_INVALID_REQUEST", "An ESTIMATION result must not carry date_of_birth.")
    else:
        if values["date_of_birth"] is None:
            fail("ERR_INVALID_REQUEST", "A VERIFICATION result requires date_of_birth.")
        if values["estimated_age_months"] is not None or values["estimation_profile_id"] is not None:
            fail("ERR_INVALID_REQUEST",
                 "A VERIFICATION result must not carry estimated_age_months or estimation_profile_id.")

    profile = None
    if method == "ESTIMATION":
        profile = db.get(db.METHOD_PROFILES, values["estimation_profile_id"])
        if profile is None:
            fail("ERR_METHOD_PROFILE_NOT_FOUND")
    if session["age_state"] not in ("PENDING", "FAILED"):
        fail("ERR_SESSION_STATE_INVALID")
    policy = services.policy_of_session(session)

    if method == "ESTIMATION":
        mae = profile["estimation_mae_months"]
        buffer_months = calc.age_buffer_months(mae, policy["age_buffer_multiplier_bps"])
        effective = max(0, values["estimated_age_months"] - buffer_months)
        band = calc.resolve_band(effective)
        accuracy = profile["band_accuracy_bps"].get(band)
        if accuracy is None:
            fail("ERR_AGE_ACCURACY_UNDOCUMENTED")
        source_vendor_code = profile["vendor_code"]
        mae_snapshot = mae
    else:
        buffer_months = 0
        effective = _months_from_dob(values["date_of_birth"])
        band = calc.resolve_band(effective)
        accuracy = None
        source_vendor_code = None
        mae_snapshot = None
    services.require_not_lapsed(session)

    decision = "ASSURED" if effective >= policy["required_min_age_years"] * calc.MONTHS_PER_YEAR else "FAILED"
    record = {
        "session_id": session["id"],
        "method": method,
        "estimated_age_months": values["estimated_age_months"],
        "date_of_birth": values["date_of_birth"],
        "source_vendor_code": source_vendor_code,
        "mae_months_snapshot": mae_snapshot,
        "buffer_months": buffer_months,
        "effective_age_months": effective,
        "resolved_band": band,
        "documented_accuracy_bps": accuracy,
        "decision": decision,
    }
    db.insert(db.AGE_RESULTS, record, versioned=False)
    session["age_state"] = decision
    session["resolved_age_band"] = band
    db.touch(session)
    return response.object_response(views.age_result_view(record), 201)


@bp.get("/idv/verification-sessions/<session_id>/age-assurance-results")
def list_age_results(session_id):
    caller = auth.authenticate((auth.PLATFORM_ADMIN, auth.COMPLIANCE_OFFICER,
                               auth.CLIENT_INTEGRATOR, auth.MANUAL_REVIEWER))
    session = _guard(session_id, caller)
    records = derived.age_results_of_session(session["id"])
    page, limit, offset, total = support.paginated(records)
    return response.list_response([views.age_result_view(r) for r in page], limit, offset, total)


# --- step-up and completion -------------------------------------------------

@bp.post("/idv/verification-sessions/<session_id>/step-up")
def step_up(session_id):
    caller = auth.authenticate((auth.CLIENT_INTEGRATOR,))
    session = _guard(session_id, caller)
    schema.no_body()
    if session["identity_state"] != "AWAITING_EVIDENCE":
        fail("ERR_SESSION_STATE_INVALID")
    services.require_not_lapsed(session)
    policy = services.policy_of_session(session)
    if session["step_up_round"] >= policy["step_up_max_rounds"]:
        fail("ERR_STEP_UP_LIMIT_REACHED")
    session["identity_state"] = "IN_PROGRESS"
    session["step_up_round"] = session["step_up_round"] + 1
    db.touch(session)
    services.append_event(session, "STEP_UP_TRIGGERED", caller, "identity_state, step_up_round")
    return response.object_response(views.session_view(session))


@bp.post("/idv/verification-sessions/<session_id>/complete")
def complete_session(session_id):
    caller = auth.authenticate((auth.CLIENT_INTEGRATOR,))
    session = _guard(session_id, caller)
    schema.no_body()
    if session["identity_state"] != "IN_PROGRESS":
        fail("ERR_SESSION_STATE_INVALID")
    services.require_not_lapsed(session)
    attempts = derived.attempts_of_session(session["id"])
    if any(a["state"] in ("AWAITING_EVIDENCE", "SCORED", "REQUIRES_RESCORE") for a in attempts):
        fail("ERR_ATTEMPT_PENDING_FINALIZATION")
    if any(p["state"] in ("VOUCH_PENDING", "ATTESTATION_PENDING")
           for p in derived.pathways_of_session(session["id"])):
        fail("ERR_PENDING_PATHWAY_BLOCKS_COMPLETION")
    policy = services.policy_of_session(session)
    if policy["required_min_age_years"] > 0 and session["age_state"] == "PENDING":
        fail("ERR_AGE_ASSURANCE_MISSING")

    services.recompute_provisional(session)
    if session["age_state"] == "FAILED":
        services.terminate_session(session, caller, "REJECTED", "AGE_GATE_FAILED")
        return response.object_response(views.session_view(session))

    final_score = services.write_final_score(session)
    if final_score >= policy["min_assurance_score"]:
        session["identity_state"] = "VERIFIED"
        session["disposition_reason"] = "SCORE_SATISFIED"
        session["completed_at"] = clock.now()
        db.touch(session)
        services.apply_retention(session, caller)
        services.append_event(session, "SESSION_TERMINAL", caller,
                              "identity_state, disposition_reason, completed_at, assurance_score_final")
    else:
        session["identity_state"] = "MANUAL_REVIEW"
        db.touch(session)
        services.create_review_case(session, "SCORE_SHORTFALL")
        services.append_event(session, "ESCALATED_TO_REVIEW", caller,
                              "identity_state, assurance_score_final")
    return response.object_response(views.session_view(session))


# --- inclusion pathways -----------------------------------------------------

@bp.post("/idv/verification-sessions/<session_id>/alternative-pathways")
def create_pathway(session_id):
    caller = auth.authenticate((auth.CLIENT_INTEGRATOR,))
    session = _guard(session_id, caller)
    values = schema.validate(schema.read_body(), PATHWAY_FIELDS)
    if values["pathway_type"] == "VOUCHING":
        if values["voucher_reference"] is None:
            fail("ERR_INVALID_REQUEST", "A VOUCHING pathway requires voucher_reference.")
        if values["attestation_document_ref"] is not None:
            fail("ERR_INVALID_REQUEST", "A VOUCHING pathway must not carry attestation_document_ref.")
    else:
        if values["attestation_document_ref"] is None:
            fail("ERR_INVALID_REQUEST", "An ATTESTATION pathway requires attestation_document_ref.")
        if values["voucher_reference"] is not None:
            fail("ERR_INVALID_REQUEST", "An ATTESTATION pathway must not carry voucher_reference.")
    if session["identity_state"] not in ("IN_PROGRESS", "AWAITING_EVIDENCE"):
        fail("ERR_SESSION_STATE_INVALID")
    services.require_not_lapsed(session)
    policy = services.policy_of_session(session)
    if not policy["alternative_pathway_enabled"]:
        fail("ERR_ALTERNATIVE_PATHWAY_DISABLED")

    record = {
        "session_id": session["id"],
        "pathway_type": values["pathway_type"],
        "state": "VOUCH_PENDING" if values["pathway_type"] == "VOUCHING" else "ATTESTATION_PENDING",
        "voucher_reference": values["voucher_reference"],
        "attestation_document_ref": values["attestation_document_ref"],
        "reviewer_user_id": None,
        "granted_points": None,
        "decided_at": None,
    }
    db.insert(db.PATHWAYS, record)
    return response.object_response(views.pathway_view(record), 201)


@bp.get("/idv/verification-sessions/<session_id>/alternative-pathways")
def list_pathways(session_id):
    caller = auth.authenticate((auth.PLATFORM_ADMIN, auth.COMPLIANCE_OFFICER,
                               auth.CLIENT_INTEGRATOR, auth.INCLUSION_REVIEWER))
    session = _guard(session_id, caller)
    state = support.enum_filter("state", PATHWAY_STATES)
    records = derived.pathways_of_session(session["id"])
    if state is not None:
        records = [p for p in records if p["state"] == state]
    page, limit, offset, total = support.paginated(records)
    return response.list_response([views.pathway_view(p) for p in page], limit, offset, total)


# --- read-only sub-collections ---------------------------------------------

@bp.get("/idv/verification-sessions/<session_id>/biometric-templates")
def list_templates(session_id):
    auth.authenticate((auth.PLATFORM_ADMIN, auth.COMPLIANCE_OFFICER))
    session = _session_or_404(session_id)
    state = support.enum_filter("state", TEMPLATE_STATES)
    records = derived.templates_of_session(session["id"])
    if state is not None:
        records = [t for t in records if t["state"] == state]
    page, limit, offset, total = support.paginated(records)
    return response.list_response([views.biometric_template_view(t) for t in page],
                                 limit, offset, total)


@bp.get("/idv/verification-sessions/<session_id>/manual-review-cases")
def list_review_cases(session_id):
    auth.authenticate((auth.PLATFORM_ADMIN, auth.COMPLIANCE_OFFICER,
                       auth.REVIEW_MANAGER, auth.MANUAL_REVIEWER))
    session = _session_or_404(session_id)
    state = support.enum_filter("state", REVIEW_CASE_STATES)
    records = derived.review_cases_of_session(session["id"])
    if state is not None:
        records = [c for c in records if c["state"] == state]
    page, limit, offset, total = support.paginated(records)
    return response.list_response([views.review_case_view(c) for c in page], limit, offset, total)


@bp.get("/idv/verification-sessions/<session_id>/audit-events")
def list_audit_events(session_id):
    auth.authenticate((auth.PLATFORM_ADMIN, auth.COMPLIANCE_OFFICER))
    session = _session_or_404(session_id)
    event_type = support.enum_filter("event_type", EVENT_TYPES)
    records = derived.audit_events_of_session(session["id"])
    if event_type is not None:
        records = [e for e in records if e["event_type"] == event_type]
    page, limit, offset, total = support.paginated(records)
    return response.list_response([views.audit_event_view(e) for e in page], limit, offset, total)
