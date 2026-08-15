"""Member registration and lifecycle endpoints."""

from flask import Blueprint

import db
from core import (annual_cumulative_compliant, as_int, as_number, as_str, body,
                  cascade_member_dismissal, cascade_member_graduation,
                  check_frozen, check_member_conflict, get_chapter, get_member,
                  new_record, per_semester_strict_compliant, recompute_chapter,
                  recompute_member, require_fields, touch)
from db import now, now_iso, parse_dt
from errors import (ERR_DISMISSAL_REQUIRES_CAUSE, ERR_GPA_BELOW_THRESHOLD,
                    ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_STALE_MEMBER_VERSION, ApiError)
from middleware import auth, require_roles
from response import (apply_filters, list_response, serialize, serialize_many,
                      sorted_items, success)

bp = Blueprint("members", __name__)

ALL = ("ActivitiesDirector", "Advisor", "Officer", "Member")


@bp.route("/chapters/<chapterId>/members", methods=["POST"])
def register_member(chapterId):
    _, role = auth()
    require_roles(role, ("Advisor", "ActivitiesDirector"))
    ch = get_chapter(chapterId)
    check_frozen(ch)
    data = body()
    require_fields(data, ["student_id", "full_name", "email", "grade_level",
                          "weighted_gpa", "unweighted_gpa"])
    grade = as_int(data["grade_level"], "grade_level")
    if grade not in (9, 10, 11, 12):
        raise ApiError(ERR_INVALID_REQUEST, 400, "grade_level must be one of 9, 10, 11, 12")
    rec = new_record({
        "chapter_id": ch["id"],
        "student_id": as_str(data["student_id"], "student_id"),
        "full_name": as_str(data["full_name"], "full_name"),
        "email": as_str(data["email"], "email"),
        "grade_level": grade,
        "weighted_gpa": as_number(data["weighted_gpa"], "weighted_gpa"),
        "unweighted_gpa": as_number(data["unweighted_gpa"], "unweighted_gpa"),
        "status": "PROSPECTIVE",
        "inducted_cycle_id": None,
        "verified_service_hours_current_year": 0,
        "verified_service_hours_current_semester": 0,
        "probation_strikes": 0,
        "is_officer": False,
        "good_standing": False,
    })
    db.members[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/chapters/<chapterId>/members/<memberId>", methods=["GET"])
def fetch_member(chapterId, memberId):
    _, role = auth()
    require_roles(role, ALL)
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    return success(serialize(m), 200)


@bp.route("/chapters/<chapterId>/members", methods=["GET"])
def list_members(chapterId):
    _, role = auth()
    require_roles(role, ("ActivitiesDirector", "Advisor", "Officer"))
    ch = get_chapter(chapterId)
    items = [m for m in db.members.values() if m["chapter_id"] == ch["id"]]
    items = apply_filters(items, ["status", "grade_level"])
    return list_response(serialize_many(sorted_items(items)))


@bp.route("/chapters/<chapterId>/members/<memberId>/standing", methods=["GET"])
def member_standing(chapterId, memberId):
    _, role = auth()
    require_roles(role, ("ActivitiesDirector", "Advisor"))
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    return success({
        "good_standing": m["good_standing"],
        "verified_service_hours_current_year": m["verified_service_hours_current_year"],
        "verified_service_hours_current_semester": m["verified_service_hours_current_semester"],
        "probation_strikes": m["probation_strikes"],
        "annual_cumulative_compliant": annual_cumulative_compliant(m, ch),
        "per_semester_strict_compliant": per_semester_strict_compliant(m, ch),
    }, 200)


@bp.route("/chapters/<chapterId>/members/<memberId>/nominate", methods=["POST"])
def nominate_member(chapterId, memberId):
    uid, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    check_frozen(ch)
    # state legality / posture first
    if m["status"] != "PROSPECTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a PROSPECTIVE member can be nominated")
    if ch["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Chapter must be ACTIVE to nominate")
    cycle = db.cycles.get(ch["current_cycle_id"]) if ch.get("current_cycle_id") else None
    if cycle is None or cycle["status"] != "NOMINATION":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Chapter has no current cycle in NOMINATION status")
    # scheduling check second
    check_member_conflict(m["id"], parse_dt(cycle["induction_date"], "induction_date"))
    # academic check last
    if not (m["weighted_gpa"] >= ch["gpa_threshold_weighted"]
            or m["unweighted_gpa"] >= ch["gpa_threshold_unweighted"]):
        raise ApiError(ERR_GPA_BELOW_THRESHOLD, 422,
                       "Nominee GPA is below the chapter thresholds on both scales")
    m["status"] = "CANDIDATE"
    recompute_member(m)
    app = new_record({
        "chapter_id": ch["id"],
        "cycle_id": cycle["id"],
        "member_id": m["id"],
        "nominated_by_user_id": uid,
        "status": "SUBMITTED",
        "eligibility_score": None,
        "rejection_reason": None,
    })
    db.applications[app["id"]] = app
    return success(serialize(m), 200)


@bp.route("/chapters/<chapterId>/members/<memberId>/reinstate", methods=["POST"])
def reinstate_member(chapterId, memberId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    check_frozen(ch)
    if m["status"] != "ON_PROBATION":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ON_PROBATION member can be reinstated")
    for c in db.probation_cases.values():
        if c["member_id"] == m["id"] and c["status"] in ("OPEN", "APPEALED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Member has a probation case still OPEN or APPEALED")
    clock = now()
    for c in db.probation_cases.values():
        if (c["member_id"] == m["id"] and c["status"] == "RESOLVED"
                and c["outcome"] == "STANDARDS_VIOLATION_CONFIRMED"
                and c.get("probation_end_date")):
            if not clock > parse_dt(c["probation_end_date"], "probation_end_date"):
                raise ApiError(ERR_INVALID_STATE, 409,
                               "The probationary window of a confirmed case has not yet elapsed")
    m["status"] = "ACTIVE"
    recompute_member(m)
    recompute_chapter(ch)
    return success(serialize(m), 200)


@bp.route("/chapters/<chapterId>/members/<memberId>/dismiss", methods=["POST"])
def dismiss_member(chapterId, memberId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    check_frozen(ch)
    data = body()
    # order pinned by PRD 3.7: state first, then cause, then version freshness
    if m["status"] not in ("ACTIVE", "ON_PROBATION"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ACTIVE or ON_PROBATION member can be dismissed")
    if m["status"] == "ACTIVE":
        override = data.get("override_reason")
        if m["probation_strikes"] < 2 and not (isinstance(override, str) and override.strip()):
            raise ApiError(ERR_DISMISSAL_REQUIRES_CAUSE, 422,
                           "Dismissal from ACTIVE requires probation_strikes >= 2 or an override_reason")
    if "expected_member_version" not in data or data["expected_member_version"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_member_version is required")
    expected = as_int(data["expected_member_version"], "expected_member_version")
    if expected != m["version"]:
        raise ApiError(ERR_STALE_MEMBER_VERSION, 412,
                       "expected_member_version does not match the member's current version")
    m["status"] = "DISMISSED"
    cascade_member_dismissal(m)
    recompute_member(m)
    recompute_chapter(ch)
    return success(serialize(m), 200)


@bp.route("/chapters/<chapterId>/members/<memberId>/graduate", methods=["POST"])
def graduate_member(chapterId, memberId):
    _, role = auth()
    require_roles(role, ("Advisor",))
    ch = get_chapter(chapterId)
    m = get_member(ch, memberId)
    check_frozen(ch)
    if m["status"] not in ("ACTIVE", "ON_PROBATION"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ACTIVE or ON_PROBATION member can graduate")
    if m["grade_level"] != 12:
        raise ApiError(ERR_INVALID_STATE, 409, "Only grade_level 12 members can graduate")
    m["status"] = "ALUMNUS"
    cascade_member_graduation(m)
    recompute_member(m)
    recompute_chapter(ch)
    return success(serialize(m), 200)
