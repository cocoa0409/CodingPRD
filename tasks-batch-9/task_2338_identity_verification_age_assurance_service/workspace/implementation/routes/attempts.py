"""Method attempts: evidence submission, finalisation and reads (PRD 3.4 - 3.6)."""
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

bp = Blueprint("attempts", __name__)

ATTEMPT_STATES = ("AWAITING_EVIDENCE", "SCORED", "REQUIRES_RESCORE", "ACCEPTED", "REJECTED", "EXPIRED")
DOCUMENT_TYPES = ("PASSPORT", "NATIONAL_ID", "DRIVERS_LICENSE", "RESIDENCE_PERMIT")

CAPTURE_FIELDS = (
    Field("document_type", "string", required=True, enum=DOCUMENT_TYPES),
    Field("required_feature_count", "int", required=True, minimum=1, maximum=40),
    Field("passed_feature_count", "int", required=True, minimum=0, maximum=40),
    Field("tamper_signal_count", "int", required=True, minimum=0, maximum=20),
    Field("mrz_checksum_valid", "bool", required=True),
)

LIVENESS_FIELDS = (
    Field("capture_modality", "string", required=True, enum=("PASSIVE", "ACTIVE")),
    Field("pad_score_bps", "int", required=True, minimum=0, maximum=10000),
    Field("match_score_bps", "int", required=True, minimum=0, maximum=10000),
)

DATA_FIELDS = (
    Field("matched_field_count", "int", default=None, minimum=0),
    Field("total_field_count", "int", default=None, minimum=1),
    Field("correct_answer_count", "int", default=None, minimum=0),
    Field("question_count", "int", default=None, minimum=1),
)


def _attempt_and_session(attempt_id, caller):
    attempt = db.get(db.ATTEMPTS, attempt_id)
    if attempt is None:
        fail("ERR_ATTEMPT_NOT_FOUND")
    session = db.get(db.SESSIONS, attempt["session_id"])
    if session is not None:
        auth.require_own_client(caller, session["client_id"])
    return attempt, session


def _profile_of(attempt):
    return db.get(db.METHOD_PROFILES, attempt["method_profile_id"])


def _require_open_session(session):
    if session is None or session["identity_state"] != "IN_PROGRESS":
        fail("ERR_SESSION_STATE_INVALID")


def _require_no_evidence(attempt):
    if attempt.get("_has_evidence"):
        fail("ERR_EVIDENCE_ALREADY_SUBMITTED")


def _require_state_awaiting(attempt):
    if attempt["state"] != "AWAITING_EVIDENCE":
        fail("ERR_ATTEMPT_STATE_INVALID")


# --- document evidence ------------------------------------------------------

@bp.post("/idv/method-attempts/<attempt_id>/document-captures")
def create_document_capture(attempt_id):
    caller = auth.authenticate((auth.CLIENT_INTEGRATOR,))
    attempt, session = _attempt_and_session(attempt_id, caller)
    values = schema.validate(schema.read_body(), CAPTURE_FIELDS)
    if values["passed_feature_count"] > values["required_feature_count"]:
        fail("ERR_INVALID_REQUEST",
             "passed_feature_count must not exceed required_feature_count.")
    _require_open_session(session)
    _require_no_evidence(attempt)
    if attempt["method_code"] != "DOCUMENT_SCAN":
        fail("ERR_EVIDENCE_METHOD_MISMATCH")
    services.require_not_lapsed(session)
    _require_state_awaiting(attempt)

    policy = services.policy_of_session(session)
    assessed = calc.document_authenticity(
        values["passed_feature_count"], values["required_feature_count"],
        values["tamper_signal_count"], values["mrz_checksum_valid"],
        policy["doc_authenticity_floor_bps"])
    record = {
        "attempt_id": attempt["id"],
        "document_type": values["document_type"],
        "required_feature_count": values["required_feature_count"],
        "passed_feature_count": values["passed_feature_count"],
        "tamper_signal_count": values["tamper_signal_count"],
        "mrz_checksum_valid": values["mrz_checksum_valid"],
        "base_score_bps": assessed["base_score_bps"],
        "tamper_tier_multiplier_bps": assessed["tamper_tier_multiplier_bps"],
        "tamper_penalty_bps": assessed["tamper_penalty_bps"],
        "authenticity_score_bps": assessed["authenticity_score_bps"],
        "assessment": assessed["assessment"],
    }
    db.insert(db.DOCUMENT_CAPTURES, record, versioned=False)
    services.score_attempt(attempt, _profile_of(attempt), assessed["authenticity_score_bps"])
    services.recompute_provisional(session)
    return response.object_response(views.document_capture_view(record), 201)


@bp.get("/idv/method-attempts/<attempt_id>/document-captures")
def list_document_captures(attempt_id):
    caller = auth.authenticate((auth.PLATFORM_ADMIN, auth.COMPLIANCE_OFFICER,
                               auth.CLIENT_INTEGRATOR, auth.MANUAL_REVIEWER))
    attempt, _ = _attempt_and_session(attempt_id, caller)
    records = derived.captures_of_attempt(attempt["id"])
    page, limit, offset, total = support.paginated(records)
    return response.list_response([views.document_capture_view(c) for c in page],
                                 limit, offset, total)


# --- biometric evidence -----------------------------------------------------

@bp.post("/idv/method-attempts/<attempt_id>/liveness-checks")
def create_liveness_check(attempt_id):
    caller = auth.authenticate((auth.CLIENT_INTEGRATOR,))
    attempt, session = _attempt_and_session(attempt_id, caller)
    values = schema.validate(schema.read_body(), LIVENESS_FIELDS)
    _require_open_session(session)
    _require_no_evidence(attempt)
    if session["resolved_age_band"] in calc.MINOR_BANDS:
        fail("ERR_MINOR_BIOMETRIC_PROHIBITED")
    if not session["biometric_consent"]:
        fail("ERR_BIOMETRIC_CONSENT_REQUIRED")
    if attempt["method_code"] != "BIOMETRIC_COMPARISON":
        fail("ERR_EVIDENCE_METHOD_MISMATCH")
    services.require_not_lapsed(session)
    _require_state_awaiting(attempt)

    policy = services.policy_of_session(session)
    threshold, decision = calc.liveness_decision(
        policy["pad_threshold_bps"], session["risk_level"], attempt["retry_index"],
        values["capture_modality"], values["pad_score_bps"])
    record = {
        "attempt_id": attempt["id"],
        "capture_modality": values["capture_modality"],
        "pad_score_bps": values["pad_score_bps"],
        "retry_index": attempt["retry_index"],
        "effective_threshold_bps": threshold,
        "decision": decision,
    }
    db.insert(db.LIVENESS_CHECKS, record, versioned=False)

    quality = calc.biometric_quality(values["match_score_bps"], values["pad_score_bps"], decision)
    attempt["match_score_bps"] = values["match_score_bps"]
    services.score_attempt(attempt, _profile_of(attempt), quality)
    if decision != "FAIL":
        template = {
            "session_id": session["id"],
            "source_method_code": "BIOMETRIC_COMPARISON",
            "state": "STORED",
            "retention_expires_at": None,
            "deleted_at": None,
            "deletion_reason": None,
        }
        db.insert(db.BIOMETRIC_TEMPLATES, template)
    services.recompute_provisional(session)
    return response.object_response(views.liveness_check_view(record), 201)


@bp.get("/idv/method-attempts/<attempt_id>/liveness-checks")
def list_liveness_checks(attempt_id):
    caller = auth.authenticate((auth.PLATFORM_ADMIN, auth.COMPLIANCE_OFFICER,
                               auth.CLIENT_INTEGRATOR, auth.MANUAL_REVIEWER))
    attempt, _ = _attempt_and_session(attempt_id, caller)
    records = derived.liveness_checks_of_attempt(attempt["id"])
    page, limit, offset, total = support.paginated(records)
    return response.list_response([views.liveness_check_view(c) for c in page],
                                 limit, offset, total)


# --- database and knowledge-based evidence ----------------------------------

@bp.post("/idv/method-attempts/<attempt_id>/data-evidence")
def create_data_evidence(attempt_id):
    caller = auth.authenticate((auth.CLIENT_INTEGRATOR,))
    attempt, session = _attempt_and_session(attempt_id, caller)
    values = schema.validate(schema.read_body(), DATA_FIELDS)
    database_pair = (values["matched_field_count"] is not None
                     and values["total_field_count"] is not None)
    database_partial = (values["matched_field_count"] is not None
                        or values["total_field_count"] is not None)
    kba_pair = values["correct_answer_count"] is not None and values["question_count"] is not None
    kba_partial = values["correct_answer_count"] is not None or values["question_count"] is not None
    if database_partial and not database_pair:
        fail("ERR_INVALID_REQUEST",
             "matched_field_count and total_field_count must be supplied together.")
    if kba_partial and not kba_pair:
        fail("ERR_INVALID_REQUEST",
             "correct_answer_count and question_count must be supplied together.")
    if database_pair and kba_pair:
        fail("ERR_INVALID_REQUEST",
             "Supply either the database-check pair or the knowledge-based pair, not both.")
    if not database_pair and not kba_pair:
        fail("ERR_INVALID_REQUEST",
             "Supply either the database-check pair or the knowledge-based pair.")
    if database_pair and values["matched_field_count"] > values["total_field_count"]:
        fail("ERR_INVALID_REQUEST", "matched_field_count must not exceed total_field_count.")
    if kba_pair and values["correct_answer_count"] > values["question_count"]:
        fail("ERR_INVALID_REQUEST", "correct_answer_count must not exceed question_count.")
    if attempt["method_code"] == "DATABASE_CHECK" and not database_pair:
        fail("ERR_INVALID_REQUEST",
             "A DATABASE_CHECK attempt requires matched_field_count and total_field_count.")
    if attempt["method_code"] == "KNOWLEDGE_BASED" and not kba_pair:
        fail("ERR_INVALID_REQUEST",
             "A KNOWLEDGE_BASED attempt requires correct_answer_count and question_count.")
    _require_open_session(session)
    _require_no_evidence(attempt)
    if attempt["method_code"] not in ("DATABASE_CHECK", "KNOWLEDGE_BASED"):
        fail("ERR_EVIDENCE_METHOD_MISMATCH")
    services.require_not_lapsed(session)
    _require_state_awaiting(attempt)

    if database_pair:
        quality = calc.count_quality(values["matched_field_count"], values["total_field_count"])
    else:
        quality = calc.count_quality(values["correct_answer_count"], values["question_count"])
    services.score_attempt(attempt, _profile_of(attempt), quality)
    services.recompute_provisional(session)
    return response.object_response(views.attempt_view(attempt), 201)


# --- finalisation -----------------------------------------------------------

def _rejection_reason(attempt):
    if attempt["method_code"] == "DOCUMENT_SCAN":
        captures = derived.captures_of_attempt(attempt["id"])
        assessment = captures[-1]["assessment"] if captures else None
        if assessment == "FORGED":
            return "DOCUMENT_FORGED", True
        return "DOCUMENT_SUSPECT", False
    if attempt["method_code"] == "BIOMETRIC_COMPARISON":
        return "LIVENESS_FAILED", False
    if attempt["method_code"] == "DATABASE_CHECK":
        return "DATA_MISMATCH", False
    if attempt["method_code"] == "KNOWLEDGE_BASED":
        return "KBA_FAILED", False
    return None, False


@bp.post("/idv/method-attempts/<attempt_id>/finalize")
def finalize_attempt(attempt_id):
    caller = auth.authenticate((auth.CLIENT_INTEGRATOR,))
    attempt, session = _attempt_and_session(attempt_id, caller)
    schema.no_body()
    _require_open_session(session)
    services.require_not_lapsed(session)
    if attempt["state"] != "SCORED":
        fail("ERR_ATTEMPT_STATE_INVALID")

    profile = _profile_of(attempt)
    now = clock.now()
    accepted = attempt["evidence_quality_bps"] >= profile["acceptance_floor_bps"]
    if accepted:
        attempt["state"] = "ACCEPTED"
    else:
        attempt["state"] = "REJECTED"
        reason, tamper = _rejection_reason(attempt)
        attempt["rejection_reason"] = reason
        if tamper:
            attempt["tamper_flag"] = True
    attempt["finalized_at"] = now
    db.touch(attempt)
    services.recompute_provisional(session)
    services.append_event(session, "ATTEMPT_FINALIZED", caller,
                          "state, finalized_at, rejection_reason, tamper_flag")

    if not accepted and attempt["tamper_flag"]:
        session["identity_state"] = "MANUAL_REVIEW"
        db.touch(session)
        services.create_review_case(session, "FRAUD_SIGNAL")
        services.recompute_provisional(session)
        services.append_event(session, "ESCALATED_TO_REVIEW", caller,
                              "identity_state, fraud_signal_count")
    elif not accepted:
        policy = services.policy_of_session(session)
        if session["step_up_round"] < policy["step_up_max_rounds"]:
            session["identity_state"] = "AWAITING_EVIDENCE"
            db.touch(session)
            services.recompute_provisional(session)
    return response.object_response(views.attempt_view(attempt))


# --- reads ------------------------------------------------------------------

@bp.get("/idv/method-attempts/<attempt_id>")
def read_attempt(attempt_id):
    caller = auth.authenticate((auth.PLATFORM_ADMIN, auth.COMPLIANCE_OFFICER,
                               auth.CLIENT_INTEGRATOR, auth.MANUAL_REVIEWER))
    attempt, _ = _attempt_and_session(attempt_id, caller)
    return response.object_response(views.attempt_view(attempt))


@bp.get("/idv/method-attempts")
def list_attempts():
    caller = auth.authenticate((auth.PLATFORM_ADMIN, auth.COMPLIANCE_OFFICER,
                               auth.CLIENT_INTEGRATOR, auth.MANUAL_REVIEWER))
    session_id = support.string_filter("session_id")
    profile_id = support.string_filter("method_profile_id")
    state = support.enum_filter("state", ATTEMPT_STATES)
    records = db.all_of(db.ATTEMPTS)
    if caller.is_client_integrator:
        if session_id is not None:
            named = db.get(db.SESSIONS, session_id)
            if named is not None and named["client_id"] != caller.user_id:
                fail("ERR_CLIENT_SCOPE_VIOLATION")
        own = {s["id"] for s in db.SESSIONS.values() if s["client_id"] == caller.user_id}
        records = [a for a in records if a["session_id"] in own]
    if session_id is not None:
        records = [a for a in records if a["session_id"] == session_id]
    if profile_id is not None:
        records = [a for a in records if a["method_profile_id"] == profile_id]
    if state is not None:
        records = [a for a in records if a["state"] == state]
    page, limit, offset, total = support.paginated(records)
    return response.list_response([views.attempt_view(a) for a in page], limit, offset, total)
