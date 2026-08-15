"""Session and attendance endpoints."""

from flask import Blueprint, request

from db import store
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from errors import (
    ApiError, invalid_request, invalid_state, ownership_mismatch,
    ERR_SCHOOL_YEAR_NOT_OPEN, ERR_SECURITY_PLAN_NOT_ACTIVE,
    ERR_SESSION_DATE_CLOSED, ERR_SESSION_DATE_OUT_OF_YEAR,
    ERR_SESSION_DATE_IN_FUTURE, ERR_SECTION_UNSTAFFED, ERR_STUDENT_NOT_ENROLLED,
)
from services.core import (
    base_record, touch, public, get_section, get_session, parse_date,
    staffing_status, reevaluate_milestones_for_section,
)

bp = Blueprint("sessions", __name__)


@bp.route("/school/sections/<section_id>/sessions", methods=["POST"])
def create_session(section_id):
    require_roles(["SchoolAdmin"])
    section = get_section(section_id)
    body = request.get_json(silent=True) or {}
    session_date = body.get("session_date")
    if not isinstance(session_date, str):
        raise invalid_request("session_date is required")
    sd = parse_date(session_date, "session_date")

    year = store.school_years.get(section["school_year_id"])
    if year is None:
        from errors import not_found
        raise not_found("SchoolYear not found")

    # state preconditions: year OPEN
    if year["status"] != "OPEN":
        raise ApiError(ERR_SCHOOL_YEAR_NOT_OPEN, 409, "School year is not OPEN")

    # calendar rules
    ysd = parse_date(year["start_date"])
    yed = parse_date(year["end_date"])
    if not (ysd <= sd <= yed):
        raise ApiError(ERR_SESSION_DATE_OUT_OF_YEAR, 409, "session_date outside year window")
    for c in store.closures.values():
        if c["school_year_id"] != year["id"]:
            continue
        csd = parse_date(c["start_date"])
        ced = parse_date(c["end_date"])
        if csd <= sd <= ced:
            raise ApiError(ERR_SESSION_DATE_CLOSED, 409, "session_date inside a closure")

    # cross-entity: section must be staffed
    if staffing_status(section) != "STAFFED":
        raise ApiError(ERR_SECTION_UNSTAFFED, 422, "Section is UNSTAFFED")

    rec = base_record()
    rec.update({
        "section_id": section["id"],
        "session_date": session_date,
        "status": "SCHEDULED",
        "cancel_reason": None,
        "attendance": [],
    })
    store.sessions[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/school/sections/<section_id>/sessions", methods=["GET"])
def list_section_sessions(section_id):
    require_roles(["SchoolAdmin", "AssistanceOfficer", "Teacher", "Parent"])
    section = get_section(section_id)
    limit, offset = parse_pagination(request.args)
    items = [s for s in store.sessions.values() if s["section_id"] == section["id"]]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([public(s) for s in page], limit, offset, total)


@bp.route("/school/sessions/<session_id>", methods=["GET"])
def get_session_endpoint(session_id):
    require_roles(["SchoolAdmin", "AssistanceOfficer", "Teacher", "Parent"])
    rec = get_session(session_id)
    return success_object(public(rec))


@bp.route("/school/sessions/<session_id>/hold", methods=["POST"])
def hold_session(session_id):
    require_roles(["SchoolAdmin"])
    rec = get_session(session_id)
    if rec["status"] != "SCHEDULED":
        raise invalid_state("Session is not SCHEDULED")
    section = store.sections.get(rec["section_id"])
    year = store.school_years.get(section["school_year_id"]) if section else None

    # safety: ACTIVE security plan for the year
    has_active_plan = any(
        p["school_year_id"] == year["id"] and p["status"] == "ACTIVE"
        for p in store.security_plans.values()
    ) if year else False
    if not has_active_plan:
        raise ApiError(ERR_SECURITY_PLAN_NOT_ACTIVE, 409, "No ACTIVE SecurityPlan for the year")

    # temporal: session_date must be <= logical clock current date
    sd = parse_date(rec["session_date"])
    if sd > store.now().date():
        raise ApiError(ERR_SESSION_DATE_IN_FUTURE, 409, "Cannot hold a future-dated session")

    rec["status"] = "HELD"
    touch(rec)

    # every REGISTERED enrollment of this section -> ACTIVE
    for e in store.enrollments.values():
        if e["section_id"] == rec["section_id"] and e["status"] == "REGISTERED":
            e["status"] = "ACTIVE"
            touch(e)

    reevaluate_milestones_for_section(rec["section_id"])
    return success_object(public(rec))


@bp.route("/school/sessions/<session_id>/cancel", methods=["POST"])
def cancel_session(session_id):
    require_roles(["SchoolAdmin"])
    rec = get_session(session_id)
    if rec["status"] != "SCHEDULED":
        raise invalid_state("Session is not SCHEDULED")
    rec["status"] = "CANCELLED"
    rec["cancel_reason"] = "MANUAL"
    touch(rec)
    reevaluate_milestones_for_section(rec["section_id"])
    return success_object(public(rec))


@bp.route("/school/sessions/<session_id>/attendance", methods=["POST"])
def post_attendance(session_id):
    role, user_id = require_roles(["SchoolAdmin", "Teacher"])
    rec = get_session(session_id)
    section = store.sections.get(rec["section_id"])
    if role == "Teacher":
        if section is None or section.get("teacher_id") != user_id:
            raise ownership_mismatch("Teacher may only post attendance for own sections")

    body = request.get_json(silent=True) or {}
    entries = body.get("entries")
    if not isinstance(entries, list):
        raise invalid_request("entries must be an array")
    for entry in entries:
        if not isinstance(entry, dict):
            raise invalid_request("each entry must be an object")
        sid = entry.get("student_id")
        st = entry.get("status")
        if not isinstance(sid, str):
            raise invalid_request("entry.student_id must be a string")
        if st not in ("PRESENT", "ABSENT", "EXCUSED"):
            raise invalid_request("entry.status must be PRESENT, ABSENT, or EXCUSED")

    if rec["status"] != "HELD":
        raise invalid_state("Attendance may only be posted on a HELD session")

    # every entry must reference a student with REGISTERED/ACTIVE enrollment in this section
    for entry in entries:
        sid = entry["student_id"]
        enrolled = any(
            e["student_id"] == sid
            and e["section_id"] == rec["section_id"]
            and e["status"] in ("REGISTERED", "ACTIVE")
            for e in store.enrollments.values()
        )
        if not enrolled:
            raise ApiError(ERR_STUDENT_NOT_ENROLLED, 422, f"Student {sid} not enrolled in section")

    # upsert by student_id
    for entry in entries:
        sid = entry["student_id"]
        found = None
        for ex in rec["attendance"]:
            if ex["student_id"] == sid:
                found = ex
                break
        if found is None:
            rec["attendance"].append({"student_id": sid, "status": entry["status"]})
        else:
            found["status"] = entry["status"]
    touch(rec)

    reevaluate_milestones_for_section(rec["section_id"])
    return success_object(public(rec))
