"""Chapter lifecycle endpoints."""

from flask import Blueprint

import db
from core import (as_int, as_number, as_str, body, check_frozen, get_chapter,
                  new_record, recompute_chapter, require_fields, touch)
from errors import ERR_INVALID_STATE, ApiError
from middleware import auth, require_roles
from response import apply_filters, list_response, serialize_many, serialize, sorted_items, success

bp = Blueprint("chapters", __name__)

ALL = ("ActivitiesDirector", "Advisor", "Officer", "Member")


@bp.route("/chapters", methods=["POST"])
def create_chapter():
    _, role = auth()
    require_roles(role, ("ActivitiesDirector",))
    data = body()
    require_fields(data, ["school_name", "charter_number", "advisor_user_id",
                          "gpa_threshold_weighted", "gpa_threshold_unweighted",
                          "service_hours_annual_required",
                          "service_hours_per_semester_required",
                          "national_dues_cents_per_member"])
    rec = new_record({
        "school_name": as_str(data["school_name"], "school_name"),
        "charter_number": as_str(data["charter_number"], "charter_number"),
        "advisor_user_id": as_str(data["advisor_user_id"], "advisor_user_id"),
        "gpa_threshold_weighted": as_number(data["gpa_threshold_weighted"], "gpa_threshold_weighted"),
        "gpa_threshold_unweighted": as_number(data["gpa_threshold_unweighted"], "gpa_threshold_unweighted"),
        "service_hours_annual_required": as_int(data["service_hours_annual_required"], "service_hours_annual_required"),
        "service_hours_per_semester_required": as_int(data["service_hours_per_semester_required"], "service_hours_per_semester_required"),
        "national_dues_cents_per_member": as_int(data["national_dues_cents_per_member"], "national_dues_cents_per_member"),
        "status": "DRAFT",
        "standing": "GOOD_STANDING",
        "current_cycle_id": None,
        "fund_balance_cents": 0,
        "dues_arrears_cents": 0,
        "active_member_count": 0,
    })
    db.chapters[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/chapters/<chapterId>", methods=["GET"])
def fetch_chapter(chapterId):
    _, role = auth()
    require_roles(role, ALL)
    ch = get_chapter(chapterId)
    return success(serialize(ch), 200)


@bp.route("/chapters", methods=["GET"])
def list_chapters():
    _, role = auth()
    require_roles(role, ALL)
    items = apply_filters(db.chapters.values(), ["status"])
    return list_response(serialize_many(sorted_items(items)))


@bp.route("/chapters/<chapterId>/activate", methods=["POST"])
def activate_chapter(chapterId):
    _, role = auth()
    require_roles(role, ("ActivitiesDirector",))
    ch = get_chapter(chapterId)
    if ch["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT chapter can be activated")
    if not ch["advisor_user_id"]:
        raise ApiError(ERR_INVALID_STATE, 409, "advisor_user_id must be non-empty to activate")
    if ch["gpa_threshold_weighted"] < ch["gpa_threshold_unweighted"]:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "gpa_threshold_weighted must be at least gpa_threshold_unweighted")
    if ch["service_hours_annual_required"] < 2 * ch["service_hours_per_semester_required"]:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "service_hours_annual_required must be at least twice service_hours_per_semester_required")
    ch["status"] = "ACTIVE"
    ch["standing"] = "GOOD_STANDING"
    touch(ch)
    return success(serialize(ch), 200)


@bp.route("/chapters/<chapterId>/suspend", methods=["POST"])
def suspend_chapter(chapterId):
    _, role = auth()
    require_roles(role, ("ActivitiesDirector",))
    ch = get_chapter(chapterId)
    if ch["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACTIVE chapter can be suspended")
    ch["status"] = "SUSPENDED"
    touch(ch)
    return success(serialize(ch), 200)


@bp.route("/chapters/<chapterId>/reinstate", methods=["POST"])
def reinstate_chapter(chapterId):
    _, role = auth()
    require_roles(role, ("ActivitiesDirector",))
    ch = get_chapter(chapterId)
    if ch["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SUSPENDED chapter can be reinstated")
    open_cases = [c for c in db.probation_cases.values()
                  if c["chapter_id"] == ch["id"] and c["status"] == "OPEN"]
    if open_cases:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "All OPEN probation cases under the chapter must be RESOLVED before reinstatement")
    ch["status"] = "ACTIVE"
    touch(ch)
    return success(serialize(ch), 200)


@bp.route("/chapters/<chapterId>/dissolve", methods=["POST"])
def dissolve_chapter(chapterId):
    _, role = auth()
    require_roles(role, ("ActivitiesDirector",))
    ch = get_chapter(chapterId)
    if ch["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACTIVE chapter can be dissolved")
    if ch["fund_balance_cents"] != 0:
        raise ApiError(ERR_INVALID_STATE, 409, "fund_balance_cents must be exactly zero to dissolve")
    lingering = [m for m in db.members.values()
                 if m["chapter_id"] == ch["id"] and m["status"] not in ("ALUMNUS", "DISMISSED")]
    if lingering:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "All members must be ALUMNUS or DISMISSED before dissolution")
    open_elections = [e for e in db.elections.values()
                      if e["chapter_id"] == ch["id"] and e["status"] in ("DRAFT", "OPEN", "TALLIED")]
    if open_elections:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "No officer election may remain in DRAFT, OPEN, or TALLIED")
    # cascades
    for r in db.officer_roles.values():
        if r["chapter_id"] == ch["id"] and r["status"] == "ACTIVE":
            r["status"] = "REMOVED"
            r["ended_at"] = db.now_iso()
            touch(r)
            recompute_member_safe(r["member_id"])
    for f in db.fundraisers.values():
        if f["chapter_id"] == ch["id"] and f["status"] in (
                "DRAFT", "SUBMITTED", "ADVISOR_APPROVED", "DIRECTOR_APPROVED"):
            f["status"] = "REJECTED"
            touch(f)
    ch["status"] = "DISSOLVED"
    touch(ch)
    return success(serialize(ch), 200)


def recompute_member_safe(member_id):
    from core import recompute_member
    m = db.members.get(member_id)
    if m is not None:
        recompute_member(m)


@bp.route("/chapters/<chapterId>/standing", methods=["GET"])
def chapter_standing(chapterId):
    _, role = auth()
    require_roles(role, ("ActivitiesDirector", "Advisor"))
    ch = get_chapter(chapterId)
    return success({
        "standing": ch["standing"],
        "dues_arrears_cents": ch["dues_arrears_cents"],
        "fund_balance_cents": ch["fund_balance_cents"],
        "active_member_count": ch["active_member_count"],
    }, 200)
