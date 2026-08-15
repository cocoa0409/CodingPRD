"""CrisisShift and CrisisVisit endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_UNAUTHORIZED,
    ERR_TEMPORAL_INVALID,
    ERR_SCHEDULE_CONFLICT,
    ERR_STALE_VERSION,
    ERR_NO_CRISIS_COVERAGE,
    ERR_ROOM_OCCUPIED,
    ERR_RISK_BAND_VIOLATION,
)
from middleware import require_roles
from response import success_object, success_list
from services import domain
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    parse_iso8601,
    require_date,
    require_enum,
    require_int,
    require_string,
    require_ts,
    sort_by_created_at,
)

bp = Blueprint("crisis", __name__)

SHIFT_KINDS = {"WALK_IN", "AFTER_HOURS"}


# --- CrisisShift ---

@bp.route("/ucc/crisis-shifts", methods=["POST"])
@require_roles("ClinicalDirector")
def create_shift(_user_id: str, _role: str):
    body = get_json_body()
    coverage_date = require_date(body, "coverage_date")
    shift_kind = require_enum(body, "shift_kind", SHIFT_KINDS)
    starts_at = require_ts(body, "starts_at")
    ends_at = require_ts(body, "ends_at")

    start = parse_iso8601(starts_at, "starts_at")
    end = parse_iso8601(ends_at, "ends_at")
    if not (end > start):
        raise_err(ERR_TEMPORAL_INVALID, "ends_at must be strictly after starts_at")

    shift = {
        "coverage_date": coverage_date,
        "shift_kind": shift_kind,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "claimed_by_id": None,
        "status": "UNCLAIMED",
    }
    db.stamp_new(shift)
    db.crisis_shifts[shift["id"]] = shift
    return success_object(serialize(shift), 201)


@bp.route("/ucc/crisis-shifts/<shift_id>", methods=["GET"])
@require_roles("FrontDesk", "Counselor", "ClinicalDirector", "TriageScreener")
def get_shift(shift_id: str, _user_id: str, _role: str):
    sh = db.crisis_shifts.get(shift_id)
    if sh is None:
        raise_err(ERR_NOT_FOUND, "CrisisShift id does not exist")
    return success_object(serialize(sh))


@bp.route("/ucc/crisis-shifts", methods=["GET"])
@require_roles("FrontDesk", "Counselor", "ClinicalDirector", "TriageScreener")
def list_shifts(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.crisis_shifts.values()))
    items = apply_filters(items, ["status", "shift_kind", "coverage_date", "claimed_by_id"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/ucc/crisis-shifts/<shift_id>/claim", methods=["POST"])
@require_roles("Counselor")
def claim_shift(shift_id: str, _user_id: str, _role: str):
    sh = db.crisis_shifts.get(shift_id)
    if sh is None:
        raise_err(ERR_NOT_FOUND, "CrisisShift id does not exist")
    body = get_json_body()
    expected = require_int(body, "expected_crisis_shift_version")

    # Counselor existence + active check.
    counselor = db.counselors.get(_user_id)
    if counselor is None:
        raise_err(ERR_NOT_FOUND, "Acting counselor does not exist")
    if not counselor.get("active", True):
        raise_err(ERR_INVALID_STATE, "Counselor is not active")

    # State precondition: UNCLAIMED or RELEASED.
    if sh.get("status") not in ("UNCLAIMED", "RELEASED"):
        raise_err(ERR_INVALID_STATE, "CrisisShift is not claimable")

    # Overlap with other CLAIMED shifts held by this counselor.
    new_start = parse_iso8601(sh["starts_at"], "starts_at")
    new_end = parse_iso8601(sh["ends_at"], "ends_at")
    if domain.counselor_shift_overlap(_user_id, new_start, new_end, exclude_shift_id=sh["id"]):
        raise_err(ERR_SCHEDULE_CONFLICT, "Counselor already holds an overlapping CLAIMED shift")

    # OCC check.
    if int(expected) != int(sh.get("version", 1)):
        raise_err(ERR_STALE_VERSION, "expected_crisis_shift_version does not match")

    sh["status"] = "CLAIMED"
    sh["claimed_by_id"] = _user_id
    db.touch(sh)
    return success_object(serialize(sh))


@bp.route("/ucc/crisis-shifts/<shift_id>/release", methods=["POST"])
@require_roles("Counselor", "ClinicalDirector")
def release_shift(shift_id: str, _user_id: str, _role: str):
    sh = db.crisis_shifts.get(shift_id)
    if sh is None:
        raise_err(ERR_NOT_FOUND, "CrisisShift id does not exist")
    # Ownership: counselor must be claimed_by_id; CD bypasses.
    if _role == "Counselor" and sh.get("claimed_by_id") != _user_id:
        raise_err(ERR_UNAUTHORIZED, "Counselor may only release own claimed shifts")
    if sh.get("status") != "CLAIMED":
        raise_err(ERR_INVALID_STATE, "CrisisShift is not CLAIMED")
    # Block while a visit on this shift is IN_ROOM.
    for v in db.crisis_visits.values():
        if v.get("shift_id") == sh["id"] and v.get("status") == "IN_ROOM":
            raise_err(ERR_INVALID_STATE, "A CrisisVisit is IN_ROOM on this shift")
    sh["status"] = "RELEASED"
    sh["claimed_by_id"] = None
    db.touch(sh)
    return success_object(serialize(sh))


# --- CrisisVisit ---

@bp.route("/ucc/crisis-visits", methods=["POST"])
@require_roles("FrontDesk", "TriageScreener")
def check_in_visit(_user_id: str, _role: str):
    body = get_json_body()
    student_id = require_string(body, "student_id")
    shift_id = require_string(body, "shift_id")
    presenting_risk_band = require_enum(body, "presenting_risk_band", domain.RISK_BANDS)

    if db.students.get(student_id) is None:
        raise_err(ERR_NOT_FOUND, "student_id does not resolve")
    shift = db.crisis_shifts.get(shift_id)
    if shift is None:
        raise_err(ERR_NOT_FOUND, "shift_id does not resolve")
    if shift.get("status") != "CLAIMED":
        raise_err(ERR_NO_CRISIS_COVERAGE, "Target shift is not CLAIMED")

    visit = {
        "student_id": student_id,
        "shift_id": shift_id,
        "presenting_risk_band": presenting_risk_band,
        "status": "QUEUED",
        "disposition": "NONE",
    }
    db.stamp_new(visit)
    db.crisis_visits[visit["id"]] = visit
    return success_object(serialize(visit), 201)


@bp.route("/ucc/crisis-visits/<visit_id>", methods=["GET"])
@require_roles("Counselor", "ClinicalDirector", "TriageScreener", "FrontDesk")
def get_visit(visit_id: str, _user_id: str, _role: str):
    v = db.crisis_visits.get(visit_id)
    if v is None:
        raise_err(ERR_NOT_FOUND, "CrisisVisit id does not exist")
    return success_object(serialize(v))


@bp.route("/ucc/crisis-visits", methods=["GET"])
@require_roles("Counselor", "ClinicalDirector", "TriageScreener", "FrontDesk")
def list_visits(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.crisis_visits.values()))
    items = apply_filters(items, ["student_id", "shift_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/ucc/crisis-visits/<visit_id>/room", methods=["POST"])
@require_roles("Counselor")
def room_visit(visit_id: str, _user_id: str, _role: str):
    v = db.crisis_visits.get(visit_id)
    if v is None:
        raise_err(ERR_NOT_FOUND, "CrisisVisit id does not exist")
    shift = db.crisis_shifts.get(v.get("shift_id"))
    if shift is None:
        raise_err(ERR_NOT_FOUND, "Linked CrisisShift does not exist")
    # Ownership: only the shift's claimed counselor.
    if shift.get("claimed_by_id") != _user_id:
        raise_err(ERR_UNAUTHORIZED, "Only the claiming counselor may room a visit")
    if v.get("status") != "QUEUED":
        raise_err(ERR_INVALID_STATE, "CrisisVisit is not QUEUED")
    # Single-room serialization.
    for other in db.crisis_visits.values():
        if (
            other.get("shift_id") == shift["id"]
            and other.get("id") != v["id"]
            and other.get("status") == "IN_ROOM"
        ):
            raise_err(ERR_ROOM_OCCUPIED, "Another CrisisVisit is IN_ROOM on this shift")
    v["status"] = "IN_ROOM"
    db.touch(v)
    return success_object(serialize(v))


@bp.route("/ucc/crisis-visits/<visit_id>/stabilize", methods=["POST"])
@require_roles("Counselor")
def stabilize_visit(visit_id: str, _user_id: str, _role: str):
    v = db.crisis_visits.get(visit_id)
    if v is None:
        raise_err(ERR_NOT_FOUND, "CrisisVisit id does not exist")
    shift = db.crisis_shifts.get(v.get("shift_id"))
    if shift is None:
        raise_err(ERR_NOT_FOUND, "Linked CrisisShift does not exist")
    if shift.get("claimed_by_id") != _user_id:
        raise_err(ERR_UNAUTHORIZED, "Only the claiming counselor may stabilize a visit")
    if v.get("status") not in ("IN_ROOM", "ESCALATED"):
        raise_err(ERR_INVALID_STATE, "CrisisVisit is not IN_ROOM or ESCALATED")
    v["status"] = "STABILIZED"
    db.touch(v)
    return success_object(serialize(v))


@bp.route("/ucc/crisis-visits/<visit_id>/escalate", methods=["POST"])
@require_roles("Counselor", "ClinicalDirector")
def escalate_visit(visit_id: str, _user_id: str, _role: str):
    v = db.crisis_visits.get(visit_id)
    if v is None:
        raise_err(ERR_NOT_FOUND, "CrisisVisit id does not exist")
    shift = db.crisis_shifts.get(v.get("shift_id"))
    if shift is None:
        raise_err(ERR_NOT_FOUND, "Linked CrisisShift does not exist")
    # Counselor: must be claiming counselor. CD bypasses.
    if _role == "Counselor" and shift.get("claimed_by_id") != _user_id:
        raise_err(ERR_UNAUTHORIZED, "Only the claiming counselor may escalate")
    if v.get("status") != "STABILIZED":
        raise_err(ERR_INVALID_STATE, "CrisisVisit is not STABILIZED")
    v["status"] = "ESCALATED"
    db.touch(v)
    return success_object(serialize(v))


@bp.route("/ucc/crisis-visits/<visit_id>/disposition", methods=["POST"])
@require_roles("Counselor", "ClinicalDirector")
def disposition_visit(visit_id: str, _user_id: str, _role: str):
    v = db.crisis_visits.get(visit_id)
    if v is None:
        raise_err(ERR_NOT_FOUND, "CrisisVisit id does not exist")
    shift = db.crisis_shifts.get(v.get("shift_id"))
    if shift is None:
        raise_err(ERR_NOT_FOUND, "Linked CrisisShift does not exist")
    if _role == "Counselor" and shift.get("claimed_by_id") != _user_id:
        raise_err(ERR_UNAUTHORIZED, "Only the claiming counselor may disposition")
    body = get_json_body()
    disposition = require_enum(
        body, "disposition", {"RETURN_TO_CARE", "COMMUNITY_REFERRAL", "EMERGENCY_TRANSPORT"}
    )
    if v.get("status") != "STABILIZED":
        raise_err(ERR_INVALID_STATE, "CrisisVisit is not STABILIZED")

    v["status"] = "DISPOSITIONED"
    v["disposition"] = disposition
    db.touch(v)

    student = db.students.get(v["student_id"])
    if student is None:
        raise_err(ERR_NOT_FOUND, "Linked student does not exist")

    if disposition == "COMMUNITY_REFERRAL":
        referral = {
            "student_id": student["id"],
            "episode_id": None,
            "provider_name": None,
            "required_specialty": "GEN",
            "status": "PENDING",
            "rematch_count": 0,
        }
        db.stamp_new(referral)
        db.referrals[referral["id"]] = referral

    elif disposition == "RETURN_TO_CARE":
        # Only create a new episode if student has no OPEN episode.
        has_open = any(
            e.get("student_id") == student["id"] and e.get("status") == "OPEN"
            for e in db.episodes.values()
        )
        if not has_open:
            published = domain.any_published_policy()
            academic_term = published.get("academic_term") if published else "INTERSESSION"
            # Session limit uses presenting_risk_band in place of intake band.
            session_limit = domain.session_limit_for_episode(
                v.get("presenting_risk_band", "LOW"),
                student.get("funding_model", "STUDENT_FEE"),
                academic_term,
            )
            episode = {
                "student_id": student["id"],
                "primary_counselor_id": shift.get("claimed_by_id"),
                "intake_assessment_id": None,
                "academic_term": academic_term,
                "session_limit": session_limit,
                "sessions_consumed": 0,
                "status": "OPEN",
                "prior_episode_id": None,
                "exemption_granted": False,
                "_crisis_risk_points": _crisis_points_for_band(v.get("presenting_risk_band", "LOW")),
            }
            db.stamp_new(episode)
            db.episodes[episode["id"]] = episode
            # New non-terminal episode re-anchors the student's current term
            # (PRD §3.6); re-derive the strike recount and posture.
            domain.recompute_strikes_and_posture(student)

    elif disposition == "EMERGENCY_TRANSPORT":
        # Force-remove every ENROLLED enrollment; promote waitlists.
        domain.remove_student_enrollments_for_risk(student["id"])

    return success_object(serialize(v))


def _crisis_points_for_band(band: str) -> int:
    """Approximate risk points used for caseload when the episode originates
    from a crisis RETURN_TO_CARE (no intake). We use the band's lower bound."""
    return {
        "LOW": 0,
        "MODERATE": domain.MODERATE_MIN,
        "HIGH": domain.HIGH_MIN,
        "CRITICAL": domain.CRITICAL_MIN,
    }.get(band, 0)
