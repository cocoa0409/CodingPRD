"""Programs, cohorts, curriculum modules, facilities and instructors."""
from __future__ import annotations

from flask import Blueprint

import calc
from calc import (core_active_modules, cohort_sessions, cohort_trainees, hnum,
                  recompute_cohort_delivered_hours, recompute_cohort_seats,
                  recompute_program_counters)
from cascade import refresh_program
from errors import ApiError, bad_request
from store import new_row, serialize, store, touch
from util import D, parse_iso
from web import (ALL_ROLES, body, f_bool, f_dt, f_enum, f_id, f_int, f_num,
                 f_str, ok, ok_row, paginate, q_bool, q_enum, q_str, require,
                 require_any, resolve, MISSING)

bp = Blueprint("core", __name__)

MODULE_STATUS = ("ACTIVE", "RETIRED")
FACILITY_STATUS = ("ACTIVE", "CLOSED")
INSTRUCTOR_STATUS = ("ACTIVE", "INACTIVE")
COHORT_STATUS = ("RECRUITING", "SCHEDULED", "IN_SESSION", "GRADUATION_REVIEW",
                 "CLOSED", "CANCELLED")
COHORT_ADVANCE_TARGETS = ("SCHEDULED", "IN_SESSION", "GRADUATION_REVIEW",
                          "CLOSED", "CANCELLED")


# ==========================================================================
# Program
# ==========================================================================
@bp.post("/programs")
def create_program():
    user_id, role = require("ProgramCoordinator")
    data = body()
    name = f_str(data, "name")
    sponsor = f_str(data, "sponsor_agency")
    jurisdiction = f_str(data, "jurisdiction_code")
    budget = f_int(data, "equipment_budget_cents", min_val=0)
    row = new_row(
        "Program",
        name=name,
        sponsor_agency=sponsor,
        jurisdiction_code=jurisdiction,
        equipment_budget_cents=budget,
        equipment_committed_cents=0,
        active_member_count=0,
        pending_graduation_count=0,
    )
    store.programs[row["id"]] = row
    return ok_row(row, 201)


@bp.get("/programs/<program_id>")
def read_program(program_id):
    require_any()
    program = resolve(store.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    recompute_program_counters(program)
    return ok_row(program)


@bp.patch("/programs/<program_id>")
def patch_program(program_id):
    require("ProgramCoordinator")
    program = resolve(store.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    data = body()
    budget = f_int(data, "equipment_budget_cents", required=False, default=MISSING, min_val=0)
    sponsor = f_str(data, "sponsor_agency", required=False, default=MISSING)
    if budget is not MISSING and budget is not None:
        program["equipment_budget_cents"] = budget
    if sponsor is not MISSING and sponsor is not None:
        program["sponsor_agency"] = sponsor
    touch(program)
    return ok_row(program)


# ==========================================================================
# Cohort
# ==========================================================================
@bp.post("/cohorts")
def create_cohort():
    require("ProgramCoordinator")
    data = body()
    program_id = f_id(data, "program_id")
    cohort_code = f_str(data, "cohort_code")
    seat_capacity = f_int(data, "seat_capacity", min_val=1)
    win_start_raw, _ = f_dt(data, "session_window_start")
    win_end_raw, _ = f_dt(data, "session_window_end")
    program = resolve(store.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    for c in store.cohorts.values():
        if c["program_id"] == program_id and c["cohort_code"] == cohort_code:
            raise ApiError("ERR_DUPLICATE_SCOPED_KEY",
                           "cohort_code is already used inside this program.")
    row = new_row(
        "Cohort",
        program_id=program_id,
        cohort_code=cohort_code,
        seat_capacity=seat_capacity,
        seats_confirmed=0,
        seats_waitlisted=0,
        session_window_start=win_start_raw,
        session_window_end=win_end_raw,
        delivered_contact_hours=0.0,
        next_waitlist_position=1,
        graduation_reviewer_user_id=None,
        status="RECRUITING",
    )
    store.cohorts[row["id"]] = row
    return ok_row(row, 201)


@bp.get("/cohorts")
def list_cohorts():
    require_any()
    program_id = q_str("program_id")
    status = q_enum("status", COHORT_STATUS)
    rows = []
    for c in store.cohorts.values():
        if program_id is not None and c["program_id"] != program_id:
            continue
        if status is not None and c["status"] != status:
            continue
        recompute_cohort_seats(c)
        recompute_cohort_delivered_hours(c)
        rows.append(c)
    return paginate(rows)


@bp.get("/cohorts/<cohort_id>")
def read_cohort(cohort_id):
    require_any()
    cohort = resolve(store.cohorts, cohort_id, "ERR_COHORT_NOT_FOUND")
    recompute_cohort_seats(cohort)
    recompute_cohort_delivered_hours(cohort)
    return ok_row(cohort)


def _all_core_modules_have_session(cohort, wanted_status):
    sessions = cohort_sessions(cohort["id"])
    for mod in core_active_modules():
        if not any(s["module_id"] == mod["id"] and s["status"] == wanted_status
                   for s in sessions):
            return False
    return True


@bp.post("/cohorts/<cohort_id>/advance")
def advance_cohort(cohort_id):
    user_id, role = require("ProgramCoordinator")
    cohort = resolve(store.cohorts, cohort_id, "ERR_COHORT_NOT_FOUND")
    data = body()
    to_status = f_enum(data, "to_status", COHORT_ADVANCE_TARGETS)
    current = cohort["status"]

    allowed = {
        "RECRUITING": ("SCHEDULED", "CANCELLED"),
        "SCHEDULED": ("IN_SESSION", "CANCELLED"),
        "IN_SESSION": ("GRADUATION_REVIEW",),
        "GRADUATION_REVIEW": ("CLOSED",),
        "CLOSED": (),
        "CANCELLED": (),
    }
    if to_status not in allowed.get(current, ()):
        raise ApiError("ERR_INVALID_STATE",
                       "Cohort cannot move from %s to %s." % (current, to_status))

    recompute_cohort_seats(cohort)

    if to_status == "SCHEDULED":
        if not _all_core_modules_have_session(cohort, "SCHEDULED"):
            raise ApiError("ERR_INVALID_STATE",
                           "Every core active module needs a SCHEDULED class session.")
        cohort["status"] = "SCHEDULED"
    elif to_status == "IN_SESSION":
        if store.now() < parse_iso(cohort["session_window_start"]):
            raise ApiError("ERR_INVALID_STATE",
                           "The logical clock has not reached session_window_start.")
        cohort["status"] = "IN_SESSION"
    elif to_status == "GRADUATION_REVIEW":
        if not _all_core_modules_have_session(cohort, "DELIVERED"):
            raise ApiError("ERR_INVALID_STATE",
                           "Every core active module needs a DELIVERED class session.")
        if cohort["seats_confirmed"] < 1:
            raise ApiError("ERR_INVALID_STATE", "The cohort has no confirmed seats.")
        cohort["status"] = "GRADUATION_REVIEW"
        cohort["graduation_reviewer_user_id"] = user_id
    elif to_status == "CLOSED":
        trainees = cohort_trainees(cohort["id"])
        if any(t["enrollment_status"] == "ENROLLED" for t in trainees):
            raise ApiError("ERR_INVALID_STATE",
                           "A trainee of this cohort is still ENROLLED.")
        ids = set(t["id"] for t in trainees)
        for comp in store.module_completions.values():
            if comp["trainee_id"] in ids and comp["status"] == "SKILLS_PENDING":
                raise ApiError("ERR_INVALID_STATE",
                               "A completion is still awaiting its skills demonstration.")
        cohort["status"] = "CLOSED"
    else:  # CANCELLED
        for s in cohort_sessions(cohort["id"]):
            if s["status"] == "SCHEDULED":
                s["status"] = "CANCELLED"
                touch(s)
        for t in cohort_trainees(cohort["id"]):
            if t["enrollment_status"] in ("APPLIED", "WAITLISTED", "ENROLLED"):
                t["enrollment_status"] = "WITHDRAWN"
                touch(t)
        cohort["status"] = "CANCELLED"

    recompute_cohort_seats(cohort)
    recompute_cohort_delivered_hours(cohort)
    touch(cohort)
    refresh_program(store.programs.get(cohort["program_id"]))
    return ok_row(cohort)


# ==========================================================================
# CurriculumModule
# ==========================================================================
def _creates_cycle(module_id, prerequisite_id):
    """True when pointing module_id at prerequisite_id would make the module
    reachable from itself (self-reference included)."""
    if prerequisite_id is None:
        return False
    if prerequisite_id == module_id:
        return True
    seen = set()
    cursor = prerequisite_id
    while cursor is not None and cursor not in seen:
        seen.add(cursor)
        if cursor == module_id:
            return True
        node = store.curriculum_modules.get(cursor)
        if node is None:
            return False
        cursor = node.get("prerequisite_module_id")
    return False


@bp.post("/curriculum-modules")
def create_module():
    require("ProgramCoordinator")
    data = body()
    module_code = f_str(data, "module_code")
    title = f_str(data, "title")
    contact_hours = f_num(data, "contact_hours", gt=0, max_decimals=1)
    sequence_index = f_int(data, "sequence_index", min_val=1)
    is_core = f_bool(data, "is_core", required=False, default=True)
    requires_demo = f_bool(data, "requires_skills_demo", required=False, default=False)
    refresher = f_bool(data, "refresher_eligible", required=False, default=False)
    prerequisite = f_id(data, "prerequisite_module_id", required=False,
                        nullable=True, present=True)
    status = f_enum(data, "status", MODULE_STATUS, required=False, default="ACTIVE")
    if prerequisite is MISSING:
        prerequisite = None
    if prerequisite is not None:
        resolve(store.curriculum_modules, prerequisite, "ERR_CURRICULUM_MODULE_NOT_FOUND")
    for m in store.curriculum_modules.values():
        if m["module_code"] == module_code:
            raise ApiError("ERR_DUPLICATE_GLOBAL_KEY", "module_code is already used.")
    row = new_row(
        "CurriculumModule",
        module_code=module_code,
        title=title,
        contact_hours=float(contact_hours),
        is_core=is_core,
        requires_skills_demo=requires_demo,
        refresher_eligible=refresher,
        sequence_index=sequence_index,
        prerequisite_module_id=prerequisite,
        status=status,
    )
    if _creates_cycle(row["id"], prerequisite):
        raise ApiError("ERR_CURRICULUM_CYCLE",
                       "The prerequisite edge would create a cycle.")
    store.curriculum_modules[row["id"]] = row
    return ok_row(row, 201)


@bp.get("/curriculum-modules")
def list_modules():
    require_any()
    prerequisite = q_str("prerequisite_module_id")
    is_core = q_bool("is_core")
    status = q_enum("status", MODULE_STATUS)
    rows = []
    for m in store.curriculum_modules.values():
        if prerequisite is not None and m.get("prerequisite_module_id") != prerequisite:
            continue
        if is_core is not None and m["is_core"] != is_core:
            continue
        if status is not None and m["status"] != status:
            continue
        rows.append(m)
    return paginate(rows)


@bp.get("/curriculum-modules/<module_id>")
def read_module(module_id):
    require_any()
    module = resolve(store.curriculum_modules, module_id, "ERR_CURRICULUM_MODULE_NOT_FOUND")
    return ok_row(module)


@bp.patch("/curriculum-modules/<module_id>")
def patch_module(module_id):
    require("ProgramCoordinator")
    module = resolve(store.curriculum_modules, module_id, "ERR_CURRICULUM_MODULE_NOT_FOUND")
    data = body()
    title = f_str(data, "title", required=False, default=MISSING)
    prerequisite = f_id(data, "prerequisite_module_id", required=False,
                        nullable=True, present=True)
    status = f_enum(data, "status", MODULE_STATUS, required=False, default=MISSING)
    if prerequisite is not MISSING and prerequisite is not None:
        resolve(store.curriculum_modules, prerequisite, "ERR_CURRICULUM_MODULE_NOT_FOUND")
    if prerequisite is not MISSING and _creates_cycle(module["id"], prerequisite):
        raise ApiError("ERR_CURRICULUM_CYCLE",
                       "The prerequisite edge would create a cycle.")
    if title is not MISSING:
        module["title"] = title
    if prerequisite is not MISSING:
        module["prerequisite_module_id"] = prerequisite
    if status is not MISSING:
        module["status"] = status
    touch(module)
    return ok_row(module)


# ==========================================================================
# Facility
# ==========================================================================
@bp.post("/facilities")
def create_facility():
    require("ProgramCoordinator")
    data = body()
    name = f_str(data, "name")
    room_code = f_str(data, "room_code")
    capacity = f_int(data, "capacity_seats", min_val=1)
    status = f_enum(data, "status", FACILITY_STATUS, required=False, default="ACTIVE")
    for f in store.facilities.values():
        if f["room_code"] == room_code:
            raise ApiError("ERR_DUPLICATE_GLOBAL_KEY", "room_code is already used.")
    row = new_row("Facility", name=name, room_code=room_code,
                  capacity_seats=capacity, status=status)
    store.facilities[row["id"]] = row
    return ok_row(row, 201)


# ==========================================================================
# Instructor
# ==========================================================================
@bp.post("/instructors")
def create_instructor():
    require("ProgramCoordinator")
    data = body()
    full_name = f_str(data, "full_name")
    cert_raw, _ = f_dt(data, "certification_expires_on")
    max_daily = f_num(data, "max_daily_contact_hours", required=False, default="8", gt=0)
    status = f_enum(data, "status", INSTRUCTOR_STATUS, required=False, default="ACTIVE")
    row = new_row("Instructor", full_name=full_name,
                  certification_expires_on=cert_raw,
                  max_daily_contact_hours=float(max_daily),
                  status=status)
    store.instructors[row["id"]] = row
    return ok_row(row, 201)


@bp.patch("/instructors/<instructor_id>")
def patch_instructor(instructor_id):
    require("ProgramCoordinator")
    instructor = resolve(store.instructors, instructor_id, "ERR_INSTRUCTOR_NOT_FOUND")
    data = body()
    cert_raw, _ = f_dt(data, "certification_expires_on", required=False,
                       default=MISSING)
    max_daily = f_num(data, "max_daily_contact_hours", required=False,
                      default=None, gt=0)
    status = f_enum(data, "status", INSTRUCTOR_STATUS, required=False, default=MISSING)
    if cert_raw is not MISSING and cert_raw is not None:
        instructor["certification_expires_on"] = cert_raw
    if "max_daily_contact_hours" in data and max_daily is not None:
        instructor["max_daily_contact_hours"] = float(max_daily)
    if status is not MISSING:
        instructor["status"] = status
    touch(instructor)
    return ok_row(instructor)
