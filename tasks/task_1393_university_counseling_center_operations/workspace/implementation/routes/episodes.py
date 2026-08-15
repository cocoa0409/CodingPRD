"""CareEpisode endpoints + nested session booking."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_UNAUTHORIZED,
    ERR_STALE_VERSION,
    ERR_TEMPORAL_INVALID,
    ERR_BOOKING_SUSPENDED,
    ERR_SESSION_LIMIT_REACHED,
    ERR_COUNSELOR_OVER_CAPACITY,
    ERR_SCHEDULE_CONFLICT,
)
from middleware import require_roles
from response import success_object, success_list
from services import domain
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    optional_field,
    optional_string,
    paginate,
    parse_pagination,
    parse_iso8601,
    require_field,
    require_int,
    require_string,
    require_ts,
    sort_by_created_at,
)

bp = Blueprint("episodes", __name__)

DURATIONS = {30, 45, 60}


@bp.route("/ucc/episodes/<episode_id>", methods=["GET"])
@require_roles("Counselor", "TriageScreener", "ClinicalDirector", "FrontDesk", "ReferralCoordinator")
def get_episode(episode_id: str, _user_id: str, _role: str):
    ep = db.episodes.get(episode_id)
    if ep is None:
        raise_err(ERR_NOT_FOUND, "CareEpisode id does not exist")
    return success_object(serialize(ep))


@bp.route("/ucc/episodes", methods=["GET"])
@require_roles("Counselor", "TriageScreener", "ClinicalDirector", "FrontDesk", "ReferralCoordinator")
def list_episodes(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.episodes.values()))
    items = apply_filters(
        items,
        ["student_id", "primary_counselor_id", "status", "academic_term", "prior_episode_id", "intake_assessment_id"],
    )
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/ucc/episodes/<episode_id>/sessions", methods=["POST"])
@require_roles("FrontDesk", "Counselor")
def book_session(episode_id: str, _user_id: str, _role: str):
    # Existence: path id first.
    episode = db.episodes.get(episode_id)
    if episode is None:
        raise_err(ERR_NOT_FOUND, "CareEpisode id does not exist")
    body = get_json_body()
    counselor_id = require_string(body, "counselor_id")
    starts_at_str = require_ts(body, "starts_at")
    duration = require_int(body, "duration_minutes")
    expected_episode_version = require_int(body, "expected_episode_version")
    director_override = optional_field(body, "director_override", False)
    if not isinstance(director_override, bool):
        raise_err(ERR_INVALID_REQUEST, "director_override must be a boolean")

    counselor = db.counselors.get(counselor_id)
    if counselor is None:
        raise_err(ERR_NOT_FOUND, "counselor_id does not resolve")

    if duration not in DURATIONS:
        raise_err(ERR_INVALID_REQUEST, "duration_minutes must be one of {30, 45, 60}")

    student = db.students.get(episode.get("student_id"))
    if student is None:
        raise_err(ERR_NOT_FOUND, "Episode's student does not exist")

    # Pre-compute the new start so we can do overlap (p9) before posture (p11).
    new_start = parse_iso8601(starts_at_str, "starts_at")
    now = db.clock()

    # Schedule overlap (p9) — checked before booking posture per PRD §2.8
    # domain-gate ordering: overlap precedes the fiscal gates.
    if domain.counselor_session_overlap(counselor_id, new_start, int(duration)):
        raise_err(ERR_SCHEDULE_CONFLICT, "Counselor has an overlapping SCHEDULED/HELD session")

    # Booking-posture gate (p11)
    posture = student.get("booking_posture", "CLEAR")
    if posture == "SUSPENDED":
        raise_err(ERR_BOOKING_SUSPENDED, "Student booking_posture is SUSPENDED")
    if posture == "RESTRICTED" and not director_override:
        raise_err(ERR_BOOKING_SUSPENDED, "Student booking_posture is RESTRICTED (director_override required)")

    # Session-limit gate (p12)
    if episode.get("status") != "OPEN":
        raise_err(ERR_SESSION_LIMIT_REACHED, "Episode is not OPEN")
    if (
        episode.get("sessions_consumed", 0) >= episode.get("session_limit", 0)
        and not episode.get("exemption_granted", False)
    ):
        raise_err(ERR_SESSION_LIMIT_REACHED, "Episode session_limit reached")

    # Counselor capacity gates (p13)
    pending = domain.counselor_pending_session_count(counselor_id)
    if pending >= int(counselor.get("weekly_individual_capacity", 0)):
        raise_err(ERR_COUNSELOR_OVER_CAPACITY, "Counselor weekly capacity reached")
    ep_points = domain.episode_risk_points(episode)
    current_load = domain.counselor_caseload_load(counselor_id)
    # The episode is already assigned to a primary counselor; if this booking
    # is by the same primary counselor, the episode's points are already in
    # the load. If a different counselor delivers this session, that counselor
    # takes on the episode's risk points transiently.
    if counselor_id != episode.get("primary_counselor_id"):
        if current_load + ep_points > int(counselor.get("max_caseload_risk_points", 0)):
            raise_err(ERR_COUNSELOR_OVER_CAPACITY, "Counselor caseload risk-point cap would be exceeded")
    else:
        if current_load > int(counselor.get("max_caseload_risk_points", 0)):
            raise_err(ERR_COUNSELOR_OVER_CAPACITY, "Counselor caseload risk-point cap would be exceeded")

    # Temporal gate (p15): starts_at must be strictly in the future.
    if not (new_start > now):
        raise_err(ERR_TEMPORAL_INVALID, "Session starts_at must be strictly in the future")

    # OCC (p16)
    if expected_episode_version != int(episode.get("version", 1)):
        raise_err(ERR_STALE_VERSION, "expected_episode_version does not match episode version")

    session = {
        "episode_id": episode["id"],
        "counselor_id": counselor_id,
        "starts_at": starts_at_str,
        "duration_minutes": int(duration),
        "status": "SCHEDULED",
        "cancellation_reason": None,
        "billed_amount_cents": 0,
    }
    db.stamp_new(session)
    db.sessions[session["id"]] = session

    # Successful booking increments episode version by 1.
    db.touch(episode)

    return success_object(serialize(session), 201)


@bp.route("/ucc/episodes/<episode_id>/close", methods=["POST"])
@require_roles("Counselor", "ClinicalDirector")
def close_episode(episode_id: str, _user_id: str, _role: str):
    episode = db.episodes.get(episode_id)
    if episode is None:
        raise_err(ERR_NOT_FOUND, "CareEpisode id does not exist")
    # Ownership gate (p2.5): counselor must be primary_counselor_id; CD bypasses.
    if _role == "Counselor" and episode.get("primary_counselor_id") != _user_id:
        raise_err(ERR_UNAUTHORIZED, "Counselor may only close own episodes")
    if episode.get("status") != "OPEN":
        raise_err(ERR_INVALID_STATE, "Episode is not OPEN")
    # No linked session in SCHEDULED or HELD.
    for s in db.sessions.values():
        if s.get("episode_id") == episode["id"] and s.get("status") in ("SCHEDULED", "HELD"):
            raise_err(ERR_INVALID_STATE, "Episode has SCHEDULED or HELD sessions")
    episode["status"] = "CLOSED"
    db.touch(episode)
    # The closure may change the student's current term (PRD §3.6): the
    # strike recount is scoped to the most recently created non-terminal
    # episode, so re-derive strikes and posture for the student.
    student = db.students.get(episode.get("student_id"))
    if student is not None:
        domain.recompute_strikes_and_posture(student)
    return success_object(serialize(episode))


@bp.route("/ucc/episodes/<episode_id>/reopen", methods=["POST"])
@require_roles("Counselor", "ClinicalDirector")
def reopen_episode(episode_id: str, _user_id: str, _role: str):
    episode = db.episodes.get(episode_id)
    if episode is None:
        raise_err(ERR_NOT_FOUND, "CareEpisode id does not exist")
    if _role == "Counselor" and episode.get("primary_counselor_id") != _user_id:
        raise_err(ERR_UNAUTHORIZED, "Counselor may only reopen own episodes")

    body = get_json_body()
    intake_assessment_id = require_string(body, "intake_assessment_id")
    academic_term = require_string(body, "academic_term")

    assessment = db.intake_assessments.get(intake_assessment_id)
    if assessment is None:
        raise_err(ERR_NOT_FOUND, "intake_assessment_id does not resolve")

    if episode.get("status") != "CLOSED":
        raise_err(ERR_INVALID_STATE, "Episode is not CLOSED")

    # The referenced assessment must be for the same student, still PENDING,
    # created after this episode's closure, with band LOW or MODERATE.
    if assessment.get("student_id") != episode.get("student_id"):
        raise_err(ERR_INVALID_STATE, "Referenced intake is for a different student")
    if assessment.get("disposition") != "PENDING":
        raise_err(ERR_INVALID_STATE, "Referenced intake is not PENDING")
    if assessment.get("risk_band") not in ("LOW", "MODERATE"):
        raise_err(ERR_INVALID_STATE, "Referenced intake band is not LOW or MODERATE")
    ep_closed_at = db.parse_iso(episode["updated_at"])
    ia_created_at = db.parse_iso(assessment["created_at"])
    if not (ia_created_at > ep_closed_at):
        raise_err(ERR_INVALID_STATE, "Referenced intake was not created after this episode's closure")

    # Complete the assessment in place.
    assessment["disposition"] = "SHORT_TERM_CARE"

    # Mark THIS episode REOPENED (terminal).
    episode["status"] = "REOPENED"
    db.touch(episode)

    # Create the new episode.
    student = db.students.get(episode["student_id"])
    if student is None:
        raise_err(ERR_NOT_FOUND, "Student does not exist")
    session_limit = domain.session_limit_for_episode(
        assessment["risk_band"], student.get("funding_model", "STUDENT_FEE"), academic_term
    )
    new_episode = {
        "student_id": episode["student_id"],
        "primary_counselor_id": assessment["screener_id"],
        "intake_assessment_id": assessment["id"],
        "academic_term": academic_term,
        "session_limit": session_limit,
        "sessions_consumed": 0,
        "status": "OPEN",
        "prior_episode_id": episode["id"],
        "exemption_granted": False,
    }
    db.stamp_new(new_episode)
    db.episodes[new_episode["id"]] = new_episode
    # The new non-terminal episode re-anchors the student's current term
    # (PRD §3.6); re-derive the strike recount and posture.
    domain.recompute_strikes_and_posture(student)
    return success_object(serialize(new_episode), 201)


@bp.route("/ucc/episodes/<episode_id>/exemptions", methods=["POST"])
@require_roles("ClinicalDirector")
def grant_exemption(episode_id: str, _user_id: str, _role: str):
    episode = db.episodes.get(episode_id)
    if episode is None:
        raise_err(ERR_NOT_FOUND, "CareEpisode id does not exist")
    if episode.get("status") != "EXHAUSTED":
        raise_err(ERR_INVALID_STATE, "Episode is not EXHAUSTED")
    episode["exemption_granted"] = True
    episode["status"] = "OPEN"
    episode["session_limit"] = int(episode.get("session_limit", 0)) + domain.EXEMPTION_BONUS_SESSIONS
    db.touch(episode)
    return success_object(serialize(episode))
