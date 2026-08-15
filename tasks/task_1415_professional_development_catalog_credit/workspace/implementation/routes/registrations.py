"""Registrations: create waterfall, drop/withdraw, attendance verification,
survey, completion."""
from flask import Blueprint, request

from auth import require_role, require_any_role
from db import store, new_resource, touch, now, fiscal_year, new_id, next_seq
from envelope import ok, paginate, get_body, sort_by_created
from errors import err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE, \
    ERR_SECTION_NOT_OPEN, ERR_EMPLOYEE_NOT_ACTIVE, \
    ERR_PREREQUISITE_NOT_COMPLETED, ERR_NOT_RESOURCE_OWNER, \
    ERR_PLAN_NOT_APPROVED, ERR_PLAN_YEAR_MISMATCH, \
    ERR_REGISTRATION_NOT_YET_OPEN, ERR_REGISTRATION_WINDOW_CLOSED, \
    ERR_DUPLICATE_REGISTRATION, ERR_SCHEDULE_CONFLICT, \
    ERR_BUDGET_NOT_OPEN, ERR_BUDGET_INSUFFICIENT, \
    ERR_ATTENDANCE_INCOMPLETE, ERR_ATTENDANCE_NOT_VERIFIED, \
    ERR_SURVEY_NOT_SUBMITTED, ERR_SURVEY_ALREADY_SUBMITTED
from serializers import ser_registration, ser_attendance, ser_survey, \
    budget_available, section_seats_registered
from services import find_budget, encumber, next_waitlist_seq, \
    advance_assignments_on_registration, drop_registration, \
    complete_registration
from validate import req_str, opt_str, req_int, req_bool, \
    sy_contains

bp = Blueprint("registrations", __name__)


def get_registration_or_404(rid):
    r = store.registrations.get(rid)
    if r is None:
        raise err(ERR_NOT_FOUND, "registration not found")
    return r


def _source_course_id_of_entry(entry):
    if entry["source_type"] != "COURSE_COMPLETION":
        return None
    reg = store.registrations.get(entry["source_id"])
    if reg is None:
        return None
    section = store.sections.get(reg["section_id"])
    return section["course_id"] if section else None


def _teacher_completed_course(teacher_id, course_id):
    for e in store.transcript_entries.values():
        if (e["employee_id"] == teacher_id and e["status"] == "AWARDED"
                and e["source_type"] == "COURSE_COMPLETION"
                and _source_course_id_of_entry(e) == course_id):
            return True
    return False


def check_plan_alignment(plan, teacher_id, activity_start, activity_end=None):
    """Step 8 alignment checks shared by registrations and workshops."""
    if plan["teacher_id"] != teacher_id:
        raise err(ERR_PLAN_YEAR_MISMATCH, "plan belongs to another teacher")
    if plan["status"] not in ("APPROVED", "FULFILLED"):
        raise err(ERR_PLAN_NOT_APPROVED, "plan is not APPROVED or FULFILLED")
    if activity_end is None:
        if not sy_contains(plan["school_year"], activity_start):
            raise err(ERR_PLAN_YEAR_MISMATCH,
                      "activity date outside the plan's school year")
    else:
        from validate import sy_window_contained
        if not sy_window_contained(plan["school_year"], activity_start,
                                   activity_end):
            raise err(ERR_PLAN_YEAR_MISMATCH,
                      "activity window outside the plan's school year")


@bp.post("/pd/registrations")
def create_registration():
    ctx = require_role("Teacher", "PDCoordinator")
    body = get_body()
    # ---- step 4: request shape ----
    teacher_id = req_str(body, "teacher_id")
    section_id = req_str(body, "section_id")
    plan_id = opt_str(body, "growth_plan_id")
    focus = opt_str(body, "aligned_focus_area")
    if plan_id is not None and focus is None:
        raise err(ERR_INVALID_REQUEST,
                  "aligned_focus_area is required when growth_plan_id is present")
    if plan_id is None and focus is not None:
        raise err(ERR_INVALID_REQUEST,
                  "aligned_focus_area requires growth_plan_id")
    # ---- step 5: body FK existence ----
    emp = store.employees.get(teacher_id)
    if emp is None:
        raise err(ERR_NOT_FOUND, "teacher_id not found")
    section = store.sections.get(section_id)
    if section is None:
        raise err(ERR_NOT_FOUND, "section_id not found")
    plan = None
    if plan_id is not None:
        plan = store.growth_plans.get(plan_id)
        if plan is None:
            raise err(ERR_NOT_FOUND, "growth_plan_id not found")
    # ---- step 6: lifecycle state ----
    if emp["status"] != "ACTIVE":
        raise err(ERR_EMPLOYEE_NOT_ACTIVE, "employee is not ACTIVE")
    if section["status"] != "PUBLISHED":
        raise err(ERR_SECTION_NOT_OPEN, "section is not PUBLISHED")
    # ---- step 7: prerequisite ----
    course = store.courses.get(section["course_id"])
    prereq = course["prerequisite_course_id"] if course else None
    if prereq and not _teacher_completed_course(teacher_id, prereq):
        raise err(ERR_PREREQUISITE_NOT_COMPLETED,
                  "prerequisite course not completed")
    # ---- step 8: ownership / alignment ----
    if ctx.role == "Teacher" and ctx.user_id != teacher_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "teachers register only themselves")
    if plan is not None:
        check_plan_alignment(plan, teacher_id, section["starts_at"])
    # ---- step 9: registration window ----
    ts = now()
    if ts < section["registration_opens_at"]:
        raise err(ERR_REGISTRATION_NOT_YET_OPEN,
                  "registration window has not opened")
    if ts > section["registration_closes_at"]:
        raise err(ERR_REGISTRATION_WINDOW_CLOSED,
                  "registration window has closed")
    # ---- step 10: domain constraints ----
    for r in store.registrations.values():
        if (r["teacher_id"] == teacher_id and r["section_id"] == section_id
                and r["status"] in ("REGISTERED", "WAITLISTED")):
            raise err(ERR_DUPLICATE_REGISTRATION,
                      "teacher already has a live registration for this section")
    for r in store.registrations.values():
        if r["teacher_id"] == teacher_id and r["status"] == "REGISTERED":
            other = store.sections.get(r["section_id"])
            if other is None:
                continue
            # half-open overlap; adjacency allowed
            if section["starts_at"] < other["ends_at"] \
                    and other["starts_at"] < section["ends_at"]:
                raise err(ERR_SCHEDULE_CONFLICT,
                          "overlaps another registered section")
    # ---- seat waterfall; fiscal checks (step 11) only when taking a seat ----
    fee = section["fee_cents"]
    reg = new_resource()
    reg.update({
        "teacher_id": teacher_id,
        "section_id": section_id,
        "growth_plan_id": plan_id,
        "aligned_focus_area": focus,
        "attendance_status": "PENDING",
        "survey_status": "PENDING",
        "waitlist_seq": None,
        "encumbered_cents": 0,
        "completed_at": None,
    })
    if section_seats_registered(section) < section["seat_capacity"]:
        if fee > 0:
            budget = find_budget(emp["primary_building_id"],
                                 fiscal_year(section["starts_at"]))
            if budget is None or budget["status"] != "OPEN":
                raise err(ERR_BUDGET_NOT_OPEN,
                          "no OPEN budget for the teacher's building/year")
            if budget_available(budget) < fee:
                raise err(ERR_BUDGET_INSUFFICIENT,
                          "available_cents below the section fee")
            encumber(budget, fee)
            reg["encumbered_cents"] = fee
        reg["status"] = "REGISTERED"
    else:
        reg["status"] = "WAITLISTED"
        reg["waitlist_seq"] = next_waitlist_seq(section_id)
    store.registrations[reg["id"]] = reg
    # create cascade: compliance ASSIGNED -> IN_PROGRESS (either branch)
    advance_assignments_on_registration(teacher_id, section["course_id"])
    return ok(ser_registration(reg), 201)


@bp.get("/pd/registrations/<rid>")
def get_registration(rid):
    require_any_role()
    return ok(ser_registration(get_registration_or_404(rid)), 200)


@bp.get("/pd/registrations")
def list_registrations():
    require_any_role()
    items = store.registrations.values()
    for key in ("teacher_id", "section_id", "growth_plan_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [r for r in items if r[key] == v]
    return paginate([ser_registration(r) for r in sort_by_created(items)])


@bp.get("/pd/registrations/<rid>/attendance")
def list_registration_attendance(rid):
    require_any_role()
    r = get_registration_or_404(rid)
    items = [a for a in store.attendance.values()
             if a["registration_id"] == r["id"]]
    return paginate([ser_attendance(a) for a in sort_by_created(items)])


@bp.post("/pd/registrations/<rid>/drop")
def drop(rid):
    ctx = require_role("Teacher", "PDCoordinator")
    get_body()
    r = get_registration_or_404(rid)
    if r["status"] != "REGISTERED":
        raise err(ERR_INVALID_STATE, "only a REGISTERED registration can drop")
    section = store.sections.get(r["section_id"])
    if section["status"] not in ("PUBLISHED", "REGISTRATION_CLOSED"):
        raise err(ERR_INVALID_STATE,
                  "cannot drop while the section is in this state")
    if ctx.role == "Teacher" and ctx.user_id != r["teacher_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "not your registration")
    drop_registration(r)
    return ok(ser_registration(r), 200)


@bp.post("/pd/registrations/<rid>/withdraw")
def withdraw(rid):
    ctx = require_role("Teacher", "PDCoordinator")
    get_body()
    r = get_registration_or_404(rid)
    if r["status"] != "WAITLISTED":
        raise err(ERR_INVALID_STATE,
                  "only a WAITLISTED registration can be withdrawn")
    if ctx.role == "Teacher" and ctx.user_id != r["teacher_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "not your registration")
    r["status"] = "WITHDRAWN"
    touch(r)
    return ok(ser_registration(r), 200)


@bp.post("/pd/registrations/<rid>/verify-attendance")
def verify_attendance(rid):
    ctx = require_role("Instructor", "PDCoordinator")
    get_body()
    r = get_registration_or_404(rid)
    if r["status"] != "REGISTERED":
        raise err(ERR_INVALID_STATE, "registration is not REGISTERED")
    if r["attendance_status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "attendance already resolved")
    section = store.sections.get(r["section_id"])
    if ctx.role == "Instructor" and section["instructor_id"] != ctx.user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "not the section's instructor")
    meetings = [m for m in store.meetings.values()
                if m["section_id"] == section["id"]]
    attended = 0
    for m in meetings:
        rec_id = store.attendance_by_pair.get((r["id"], m["id"]))
        if rec_id is None:
            raise err(ERR_ATTENDANCE_INCOMPLETE,
                      "every section meeting must have a record first")
        if store.attendance[rec_id]["mark"] in ("PRESENT", "EXCUSED"):
            attended += 1
    # integer-only rate check: attended*5 >= total*4
    if attended * 5 >= len(meetings) * 4:
        r["attendance_status"] = "VERIFIED"
    else:
        r["attendance_status"] = "ABSENT"
    touch(r)
    return ok(ser_registration(r), 200)


@bp.post("/pd/registrations/<rid>/waive-survey")
def waive_survey(rid):
    require_role("PDCoordinator")
    r = get_registration_or_404(rid)
    body = get_body()
    req_str(body, "reason")
    if r["status"] != "REGISTERED":
        raise err(ERR_INVALID_STATE, "registration is not REGISTERED")
    if r["survey_status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "survey is not PENDING")
    r["survey_status"] = "WAIVED"
    touch(r)
    return ok(ser_registration(r), 200)


@bp.post("/pd/registrations/<rid>/complete")
def complete(rid):
    require_role("PDCoordinator")
    get_body()
    r = get_registration_or_404(rid)
    if r["status"] != "REGISTERED":
        raise err(ERR_INVALID_STATE, "registration is not REGISTERED")
    section = store.sections.get(r["section_id"])
    if section["status"] not in ("IN_SESSION", "COMPLETED"):
        raise err(ERR_INVALID_STATE,
                  "section must be IN_SESSION or COMPLETED")
    # completion gates, in pinned order
    if r["attendance_status"] != "VERIFIED":
        raise err(ERR_ATTENDANCE_NOT_VERIFIED, "attendance is not VERIFIED")
    if r["survey_status"] not in ("SUBMITTED", "WAIVED"):
        raise err(ERR_SURVEY_NOT_SUBMITTED,
                  "survey is neither SUBMITTED nor WAIVED")
    complete_registration(r)
    return ok(ser_registration(r), 200)


@bp.post("/pd/registrations/<rid>/survey")
def submit_survey(rid):
    ctx = require_role("Teacher")
    r = get_registration_or_404(rid)
    body = get_body()
    rating = req_int(body, "overall_rating", minimum=1, maximum=5)
    recommend = req_bool(body, "would_recommend")
    comments = opt_str(body, "comments")
    if r["status"] not in ("REGISTERED", "COMPLETED"):
        raise err(ERR_INVALID_STATE,
                  "survey requires a REGISTERED or COMPLETED registration")
    if r["survey_status"] == "WAIVED":
        raise err(ERR_INVALID_STATE, "survey was waived")
    if ctx.user_id != r["teacher_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "only the teacher may submit")
    if r["id"] in store.survey_by_registration:
        raise err(ERR_SURVEY_ALREADY_SUBMITTED,
                  "a survey already exists for this registration")
    s = {
        "id": new_id(),
        "created_at": now(),
        "registration_id": r["id"],
        "overall_rating": rating,
        "would_recommend": recommend,
        "comments": comments,
        "submitted_at": now(),
        "_seq": next_seq(),
    }
    store.surveys[s["id"]] = s
    store.survey_by_registration[r["id"]] = s["id"]
    r["survey_status"] = "SUBMITTED"
    touch(r)
    return ok(ser_survey(s), 201)


@bp.get("/pd/registrations/<rid>/survey")
def get_survey(rid):
    require_any_role()
    r = get_registration_or_404(rid)
    sid = store.survey_by_registration.get(r["id"])
    items = [store.surveys[sid]] if sid is not None else []
    return paginate([ser_survey(s) for s in items])
