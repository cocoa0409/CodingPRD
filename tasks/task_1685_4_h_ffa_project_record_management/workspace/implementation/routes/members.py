"""Member enrollment and lifecycle (PRD 3.3) plus member nested collections."""

from flask import Blueprint

import db
import response
from middleware import (authenticate, resolve_caller, must_find,
                        new_common_fields, touch)
from validation import (get_body, as_str, as_date_str, as_bool,
                        pagination_params, paginate, sort_by_creation, present)
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from services import calc
from services.serialize import (member_view, project_view, attendance_view,
                                fair_entry_view, award_application_view,
                                scholarship_app_view)

bp = Blueprint("members", __name__)

ALL_ROLES = ["ProgramAdmin", "Volunteer", "Member"]


@bp.post("/members")
def create_member():
    role, user_id = authenticate(["Volunteer", "ProgramAdmin"])
    body = get_body()
    # Priority 3: referenced identifiers exist (club_id).
    if isinstance(body.get("club_id"), str):
        must_find("clubs", body["club_id"], "Club")
    resolve_caller(role, user_id)
    # Priority 14: request shape.
    full_name = as_str(body, "full_name")
    birth_date = as_date_str(body, "birth_date")
    club_id = present(body, "club_id")
    if not isinstance(club_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'club_id': must be a string")
    club = must_find("clubs", club_id, "Club")
    is_officer = as_bool(body, "is_club_officer", default=False)
    rec = new_common_fields()
    rec.update({
        "full_name": full_name,
        "birth_date": birth_date,
        "club_id": club["id"],
        "enrollment_status": "ENROLLED",
        "is_club_officer": is_officer,
        "eligibility_posture": "INELIGIBLE",
    })
    db.table("members")[rec["id"]] = rec
    return response.success(member_view(rec), status=201)


@bp.get("/members/<mid>")
def get_member(mid):
    role, user_id = authenticate(ALL_ROLES)
    rec = must_find("members", mid, "Member")
    resolve_caller(role, user_id)
    return response.success(member_view(rec))


def _get_member_for_action(mid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("members", mid, "Member")
    resolve_caller(role, user_id)
    return rec


@bp.post("/members/<mid>/activate")
def activate_member(mid):
    rec = _get_member_for_action(mid)
    # Priority 5: ENROLLED -> ACTIVE, and the member's club must be ACTIVE.
    if rec["enrollment_status"] != "ENROLLED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Member enrollment_status must be ENROLLED to activate")
    club = db.table("clubs").get(rec["club_id"])
    if club is None or club["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Member can only be activated while their club is ACTIVE")
    rec["enrollment_status"] = "ACTIVE"
    calc.recompute_member_posture(rec, bump=False)
    touch(rec)
    return response.success(member_view(rec))


@bp.post("/members/<mid>/suspend")
def suspend_member(mid):
    rec = _get_member_for_action(mid)
    if rec["enrollment_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Member enrollment_status must be ACTIVE to suspend")
    rec["enrollment_status"] = "SUSPENDED"
    # Suspension is the system's big eraser: posture forced to INELIGIBLE and
    # every PLANNED/ACTIVE project of the member drops (each dropped project
    # advances its own version and updated_at, PRD 2.4).
    rec["eligibility_posture"] = "INELIGIBLE"
    for project in db.table("projects").values():
        if project["member_id"] == rec["id"] and project["status"] in ("PLANNED", "ACTIVE"):
            was_active = project["status"] == "ACTIVE"
            project["status"] = "DROPPED"
            touch(project)
            # Dropping an ACTIVE project rejects its record book if that book
            # is still in flight; APPROVED or REJECTED books are untouched
            # (PRD 3.4 applies to every drop, including the suspend cascade).
            if was_active:
                for rb in db.table("record_books").values():
                    if (rb["project_id"] == project["id"]
                            and rb["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "RETURNED")):
                        rb["status"] = "REJECTED"
                        touch(rb)
    touch(rec)
    return response.success(member_view(rec))


@bp.post("/members/<mid>/reinstate")
def reinstate_member(mid):
    rec = _get_member_for_action(mid)
    if rec["enrollment_status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Member enrollment_status must be SUSPENDED to reinstate")
    rec["enrollment_status"] = "ACTIVE"
    calc.recompute_member_posture(rec, bump=False)
    touch(rec)
    return response.success(member_view(rec))


@bp.post("/members/<mid>/graduate")
def graduate_member(mid):
    rec = _get_member_for_action(mid)
    if rec["enrollment_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Member enrollment_status must be ACTIVE to graduate")
    # Graduation requires no fair entry still in ENTERED or CONFIRMED status.
    open_entry = any(e["member_id"] == rec["id"]
                     and e["status"] in ("ENTERED", "CONFIRMED")
                     for e in db.table("fair_entries").values())
    if open_entry:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Member holds a fair entry still in ENTERED or CONFIRMED status")
    rec["enrollment_status"] = "GRADUATED"
    rec["eligibility_posture"] = "INELIGIBLE"
    touch(rec)
    return response.success(member_view(rec))


def _list_member_children(mid, table_name, view, filter_field):
    role, user_id = authenticate(ALL_ROLES)
    member = must_find("members", mid, "Member")
    resolve_caller(role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation(
        [r for r in db.table(table_name).values()
         if r[filter_field] == member["id"]])
    page, meta = paginate(items, limit, offset)
    return response.success([view(r) for r in page],
                            response_type="array", pagination=meta)


@bp.get("/members/<mid>/projects")
def list_member_projects(mid):
    return _list_member_children(mid, "projects", project_view, "member_id")


@bp.get("/members/<mid>/attendance")
def list_member_attendance(mid):
    return _list_member_children(mid, "attendance", attendance_view, "member_id")


@bp.get("/members/<mid>/fair-entries")
def list_member_fair_entries(mid):
    return _list_member_children(mid, "fair_entries", fair_entry_view, "member_id")


@bp.get("/members/<mid>/award-applications")
def list_member_award_applications(mid):
    return _list_member_children(mid, "award_applications", award_application_view, "member_id")


@bp.get("/members/<mid>/scholarship-apps")
def list_member_scholarship_apps(mid):
    return _list_member_children(mid, "scholarship_apps", scholarship_app_view, "member_id")
