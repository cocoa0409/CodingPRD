"""Break-glass emergency access endpoints (PRD 3.8)."""
from flask import Blueprint, request

from db import clock, create, db, fmt_dt, plus_minutes, touch
from errors import ApiError
from middleware import (
    CLINICIAN,
    HIE_ADMIN,
    PRIVACY_OFFICER,
    authenticate,
    require_scope,
)
from response import entity, entity_created, paginate, pagination
from services import repo, sanctions
from validate import body, opt_str, req_enum, req_str

bp = Blueprint("breakglass", __name__)

EMERGENCY_CATEGORIES = ("LIFE_THREATENING", "UNCONSCIOUS_PATIENT", "DISASTER")
REVIEW_OUTCOMES = ("JUSTIFIED", "UNJUSTIFIED")
TERMINAL_SESSION_STATES = ("CLOSED", "EXPIRED")
TERMINAL_REVIEW_STATES = ("JUSTIFIED", "UNJUSTIFIED")
MIN_CHARS = sanctions.BREAK_GLASS_JUSTIFICATION_MIN_CHARS


@bp.route("/hie/break-glass-accesses", methods=["POST"])
def invoke_session():
    actor = authenticate((CLINICIAN,))
    payload = body()
    raw_participant = payload.get("invoking_participant_id")
    if isinstance(raw_participant, str):
        require_scope(actor, raw_participant)

    cluster_id = req_str(payload, "cluster_id")
    invoking_participant_id = req_str(payload, "invoking_participant_id")
    category = req_enum(payload, "emergency_category", EMERGENCY_CATEGORIES)
    justification = req_str(payload, "justification_text")

    cluster = repo.must("clusters", cluster_id)
    participant = repo.must("participants", invoking_participant_id)

    if participant["onboarding_status"] != "CERTIFIED":
        raise ApiError("ERR_PARTICIPANT_NOT_CERTIFIED")
    if cluster["status"] != "ACTIVE":
        raise ApiError("ERR_CLUSTER_MERGED_AWAY")
    if sanctions.cooldown_blocked(cluster["id"], actor.user_id):
        raise ApiError("ERR_BREAK_GLASS_COOLDOWN_ACTIVE")
    if len(justification.strip()) < MIN_CHARS:
        raise ApiError("ERR_JUSTIFICATION_TOO_SHORT")

    opened_at = clock()
    expires_at = plus_minutes(opened_at, sanctions.BREAK_GLASS_SESSION_MINUTES)
    row = create(
        db.break_glass,
        "BreakGlassAccess",
        {
            "cluster_id": cluster["id"],
            "invoking_participant_id": participant["id"],
            "invoking_clinician_user_id": actor.user_id,
            "emergency_category": category,
            "justification_text": justification,
            "opened_at": fmt_dt(opened_at),
            "expires_at": fmt_dt(expires_at),
            "session_status": "OPEN",
            "review_status": "PENDING_REVIEW",
            "review_claimed_by_user_id": None,
            "reviewer_user_id": None,
            "review_note": None,
            "decided_at": None,
            "disclosed_record_count": 0,
            "disclosed_sensitive_count": 0,
            "sanction_points_awarded": 0,
        },
    )
    return entity_created(row)


@bp.route("/hie/break-glass-accesses/<session_id>/closure", methods=["POST"])
def close_session(session_id):
    actor = authenticate((CLINICIAN,))
    body()
    session = repo.must("break_glass", session_id)
    sanctions.expire_if_due(session)

    if session["session_status"] in TERMINAL_SESSION_STATES:
        raise ApiError("ERR_TERMINAL_STATE")
    if session["invoking_clinician_user_id"] != actor.user_id:
        raise ApiError("ERR_BREAK_GLASS_SESSION_NOT_OPEN")
    if session["session_status"] != "OPEN":
        raise ApiError("ERR_BREAK_GLASS_SESSION_NOT_OPEN")

    session["session_status"] = "CLOSED"
    sanctions.recompute_session_disclosures(session)
    touch(session)
    return entity(session)


@bp.route("/hie/break-glass-accesses/<session_id>/review-claim", methods=["POST"])
def claim_review(session_id):
    actor = authenticate((PRIVACY_OFFICER,))
    body()
    session = repo.must("break_glass", session_id)
    sanctions.expire_if_due(session)

    if session["review_status"] in TERMINAL_REVIEW_STATES:
        raise ApiError("ERR_TERMINAL_STATE")
    if (
        session["review_claimed_by_user_id"] is not None
        and session["review_claimed_by_user_id"] != actor.user_id
    ):
        raise ApiError("ERR_REVIEW_NOT_CLAIMED_BY_ACTOR")
    if session["review_status"] != "PENDING_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if actor.user_id == session["invoking_clinician_user_id"]:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    session["review_status"] = "UNDER_REVIEW"
    session["review_claimed_by_user_id"] = actor.user_id
    touch(session)
    return entity(session)


@bp.route("/hie/break-glass-accesses/<session_id>/review-decision", methods=["POST"])
def decide_review(session_id):
    actor = authenticate((PRIVACY_OFFICER,))
    payload = body()
    outcome = req_enum(payload, "outcome", REVIEW_OUTCOMES)
    note = req_str(payload, "review_note")

    session = repo.must("break_glass", session_id)
    sanctions.expire_if_due(session)

    if session["review_status"] in TERMINAL_REVIEW_STATES:
        raise ApiError("ERR_TERMINAL_STATE")
    if session["review_status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if outcome == "UNJUSTIFIED" and len(note.strip()) < MIN_CHARS:
        raise ApiError("ERR_JUSTIFICATION_TOO_SHORT")
    if session["review_claimed_by_user_id"] != actor.user_id:
        raise ApiError("ERR_REVIEW_NOT_CLAIMED_BY_ACTOR")

    session["review_status"] = outcome
    session["reviewer_user_id"] = actor.user_id
    session["review_note"] = note
    session["decided_at"] = fmt_dt(clock())
    if outcome == "JUSTIFIED":
        session["sanction_points_awarded"] = 0
    else:
        session["sanction_points_awarded"] = sanctions.award_for(session)
    touch(session)
    sanctions.mark_audit_reviewed(session)

    participant = repo.participant(session["invoking_participant_id"])
    if participant is not None:
        sanctions.refresh_and_maybe_suspend(participant)
    return entity(session)


@bp.route("/hie/break-glass-accesses/<session_id>", methods=["GET"])
def read_session(session_id):
    authenticate((PRIVACY_OFFICER, HIE_ADMIN, CLINICIAN))
    session = repo.must("break_glass", session_id)
    sanctions.expire_if_due(session)
    return entity(session)


@bp.route("/hie/break-glass-accesses", methods=["GET"])
def list_sessions():
    authenticate((PRIVACY_OFFICER, HIE_ADMIN))
    limit, offset = pagination()
    rows = repo.all_rows("break_glass")
    for row in rows:
        sanctions.expire_if_due(row)
    for key in (
        "cluster_id",
        "invoking_participant_id",
        "session_status",
        "review_status",
    ):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, limit, offset)
