"""Routes for SystemClock, Program, Cohort, Student, ExternshipSite."""
from flask import Blueprint

from db import store
from errors import err
from middleware import require_role, ALL_ROLES
from helpers import (
    get_json_body, serialize, stamp_new, bump, paginate, sorted_collection,
    find_or_404, as_int, as_str, as_bool, as_number, as_enum,
)
from response import success
import services
from flask import request

bp = Blueprint("config", __name__)


# ==========================================================================
# SystemClock
# ==========================================================================
@bp.get("/v1/clock")
def get_clock():
    require_role(ALL_ROLES)
    return success(serialize(store.clock()), 200)


@bp.post("/v1/clock/advance")
def advance_clock():
    require_role(["SystemAdmin"])
    body = get_json_body()
    to_term = as_int(body, "to_term_index", required=True, minimum=0)
    clock = store.clock()
    if to_term < clock["current_term_index"]:
        raise err("ERR_INVALID_REQUEST", "to_term_index must be >= current_term_index.")
    clock["current_term_index"] = to_term
    bump(clock)
    return success(serialize(clock), 200)


# ==========================================================================
# Program
# ==========================================================================
@bp.post("/v1/programs")
def create_program():
    require_role(["SystemAdmin"])
    body = get_json_body()
    name = as_str(body, "name", required=True)
    credential_type = as_enum(body, "credential_type",
                              {"DIPLOMA", "CERTIFICATE", "ASSOCIATE"}, required=True)
    required_clock = as_int(body, "required_clock_hours", required=True, minimum=1)
    required_theory = as_int(body, "required_theory_hours", required=True, minimum=0)
    required_externship = as_int(body, "required_externship_hours", required=True, minimum=0)
    tuition = as_int(body, "tuition_cents", required=True, minimum=0)

    if required_theory > required_clock:
        raise err("ERR_INVALID_REQUEST",
                  "required_theory_hours must be <= required_clock_hours.")
    if required_theory + required_externship > required_clock:
        raise err("ERR_INVALID_REQUEST",
                  "required_theory_hours + required_externship_hours must be "
                  "<= required_clock_hours.")

    sap_warning = as_number(body, "sap_warning_min_pace_pct", required=False,
                            default=0.667, exclusive_min=0, maximum=1)
    sap_probation = as_number(body, "sap_probation_min_pace_pct", required=False,
                              default=0.5, exclusive_min=0, maximum=1)
    licensure_min = as_number(body, "licensure_min_attendance_pct", required=False,
                              default=0.9, exclusive_min=0, maximum=1)
    # probation < warning <= 1
    if not (sap_probation < sap_warning):
        raise err("ERR_INVALID_REQUEST",
                  "sap_probation_min_pace_pct must be strictly less than "
                  "sap_warning_min_pace_pct.")

    program = {
        "name": name,
        "credential_type": credential_type,
        "required_clock_hours": required_clock,
        "required_theory_hours": required_theory,
        "required_externship_hours": required_externship,
        "tuition_cents": tuition,
        "sap_warning_min_pace_pct": sap_warning,
        "sap_probation_min_pace_pct": sap_probation,
        "licensure_min_attendance_pct": licensure_min,
        "status": "DRAFT",
    }
    stamp_new(program)
    store.programs[program["id"]] = program
    return success(serialize(program), 201)


@bp.get("/v1/programs")
def list_programs():
    require_role(ALL_ROLES)
    status = request.args.get("status")
    items = sorted_collection(
        store.programs,
        predicate=(lambda e: e["status"] == status) if status else None)
    page, meta = paginate(items)
    return success([serialize(e) for e in page], 200, pagination=meta)


@bp.get("/v1/programs/<pid>")
def get_program(pid):
    require_role(ALL_ROLES)
    program = find_or_404(store.programs, pid, "Program")
    return success(serialize(program), 200)


@bp.post("/v1/programs/<pid>/open")
def open_program(pid):
    require_role(["SystemAdmin"])
    program = find_or_404(store.programs, pid, "Program")
    if program["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Program must be DRAFT to open.")
    program["status"] = "OPEN"
    bump(program)
    return success(serialize(program), 200)


@bp.post("/v1/programs/<pid>/close")
def close_program(pid):
    require_role(["SystemAdmin"])
    program = find_or_404(store.programs, pid, "Program")
    if program["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Program must be OPEN to close.")
    program["status"] = "CLOSED"
    bump(program)
    return success(serialize(program), 200)


@bp.get("/v1/programs/<pid>/placement-report")
def placement_report(pid):
    require_role(["Registrar", "AcademicAdvisor", "SystemAdmin"])
    program = find_or_404(store.programs, pid, "Program")
    grads = [a for a in store.enrollment_agreements.values()
             if a["program_id"] == program["id"] and a["status"] == "GRADUATED"]
    placeable = len(grads)
    placed = 0
    for a in grads:
        outcomes = [o for o in store.placement_outcomes.values()
                    if o["agreement_id"] == a["id"]]
        if not outcomes:
            continue
        # latest by outcome_term_index, tie-break later created_at then _seq
        outcomes.sort(key=lambda o: (o["outcome_term_index"], o["created_at"],
                                     o.get("_seq", 0)))
        latest = outcomes[-1]
        if latest["counts_as_placed"]:
            placed += 1
    if placeable > 0:
        from helpers import round_half_up_4
        rate = round_half_up_4(placed / placeable)
    else:
        rate = 0.0
    return success({
        "program_id": program["id"],
        "graduated_count": placeable,
        "placed_count": placed,
        "placement_rate_pct": rate,
    }, 200)


# ==========================================================================
# Cohort
# ==========================================================================
@bp.post("/v1/cohorts")
def create_cohort():
    require_role(["Registrar"])
    body = get_json_body()
    program_id = as_str(body, "program_id", required=True)
    code = as_str(body, "code", required=True)
    start_idx = as_int(body, "start_term_index", required=True, minimum=0)
    end_idx = as_int(body, "end_term_index", required=True)
    seat_capacity = as_int(body, "seat_capacity", required=True, minimum=1)
    if end_idx <= start_idx:
        raise err("ERR_INVALID_REQUEST", "end_term_index must be > start_term_index.")

    program = find_or_404(store.programs, program_id, "Program")
    if program["status"] != "OPEN":
        raise err("ERR_PROGRAM_NOT_OPEN", "Cohort creation requires an OPEN program.")

    cohort = {
        "program_id": program_id,
        "code": code,
        "start_term_index": start_idx,
        "end_term_index": end_idx,
        "seat_capacity": seat_capacity,
        "enrolled_count": 0,
        "status": "FORMING",
    }
    stamp_new(cohort)
    store.cohorts[cohort["id"]] = cohort
    return success(serialize(cohort), 201)


@bp.get("/v1/cohorts")
def list_cohorts():
    require_role(ALL_ROLES)
    program_id = request.args.get("program_id")
    status = request.args.get("status")

    def pred(e):
        if program_id and e["program_id"] != program_id:
            return False
        if status and e["status"] != status:
            return False
        return True

    items = sorted_collection(store.cohorts, predicate=pred)
    page, meta = paginate(items)
    return success([serialize(e) for e in page], 200, pagination=meta)


@bp.get("/v1/cohorts/<cid>")
def get_cohort(cid):
    require_role(ALL_ROLES)
    cohort = find_or_404(store.cohorts, cid, "Cohort")
    return success(serialize(cohort), 200)


@bp.post("/v1/cohorts/<cid>/start")
def start_cohort(cid):
    require_role(["Registrar"])
    cohort = find_or_404(store.cohorts, cid, "Cohort")
    if cohort["status"] != "FORMING":
        raise err("ERR_INVALID_STATE", "Cohort must be FORMING to start.")
    program = store.programs[cohort["program_id"]]
    if program["status"] != "OPEN":
        raise err("ERR_PROGRAM_NOT_OPEN", "Cohort start requires an OPEN program.")
    if store.clock()["current_term_index"] < cohort["start_term_index"]:
        raise err("ERR_COHORT_NOT_STARTED",
                  "Clock has not reached the cohort's start_term_index.")
    cohort["status"] = "RUNNING"
    bump(cohort)
    return success(serialize(cohort), 200)


@bp.post("/v1/cohorts/<cid>/complete")
def complete_cohort(cid):
    require_role(["Registrar"])
    cohort = find_or_404(store.cohorts, cid, "Cohort")
    if cohort["status"] != "RUNNING":
        raise err("ERR_INVALID_STATE", "Cohort must be RUNNING to complete.")
    for a in store.enrollment_agreements.values():
        if a["cohort_id"] == cohort["id"] and a["status"] in ("ENROLLED", "LEAVE_OF_ABSENCE"):
            raise err("ERR_OPEN_AGREEMENTS_EXIST",
                      "Cohort has open (ENROLLED/LEAVE_OF_ABSENCE) agreements.")
    cohort["status"] = "COMPLETED"
    bump(cohort)
    return success(serialize(cohort), 200)


# ==========================================================================
# Student
# ==========================================================================
@bp.post("/v1/students")
def create_student():
    require_role(["Registrar"])
    body = get_json_body()
    full_name = as_str(body, "full_name", required=True)
    email = as_str(body, "email", required=True)
    hs_verified = as_bool(body, "hs_diploma_verified", required=False, default=False)

    # case-insensitive email uniqueness
    for s in store.students.values():
        if s["email"].lower() == email.lower():
            raise err("ERR_DUPLICATE_KEY", "Student email already exists.")

    student = {
        "full_name": full_name,
        "email": email,
        "hs_diploma_verified": hs_verified,
    }
    stamp_new(student)
    store.students[student["id"]] = student
    return success(serialize(student), 201)


@bp.get("/v1/students")
def list_students():
    require_role(ALL_ROLES)
    email = request.args.get("email")
    items = sorted_collection(
        store.students,
        predicate=(lambda e: e["email"].lower() == email.lower()) if email else None)
    page, meta = paginate(items)
    return success([serialize(e) for e in page], 200, pagination=meta)


@bp.get("/v1/students/<sid>")
def get_student(sid):
    require_role(ALL_ROLES)
    student = find_or_404(store.students, sid, "Student")
    return success(serialize(student), 200)


@bp.patch("/v1/students/<sid>")
def update_student(sid):
    require_role(["Registrar"])
    student = find_or_404(store.students, sid, "Student")
    body = get_json_body()
    # OCC (optional) on student version
    if "expected_student_version" in body and body["expected_student_version"] is not None:
        exp = as_int(body, "expected_student_version", required=True)
        if exp != student["version"]:
            raise err("ERR_STALE_VERSION", "Student version mismatch.")
    if "hs_diploma_verified" in body and body["hs_diploma_verified"] is not None:
        student["hs_diploma_verified"] = as_bool(body, "hs_diploma_verified", required=True)
    if "full_name" in body and body["full_name"] is not None:
        student["full_name"] = as_str(body, "full_name", required=True)
    bump(student)
    return success(serialize(student), 200)


# ==========================================================================
# ExternshipSite
# ==========================================================================
@bp.post("/v1/externship-sites")
def create_site():
    require_role(["AcademicAdvisor", "SystemAdmin"])
    body = get_json_body()
    name = as_str(body, "name", required=True)
    capacity = as_int(body, "daily_slot_capacity", required=True, minimum=1)
    site = {
        "name": name,
        "daily_slot_capacity": capacity,
        "active_assignment_count": 0,
        "status": "ACTIVE",
    }
    stamp_new(site)
    store.externship_sites[site["id"]] = site
    return success(serialize(site), 201)


@bp.get("/v1/externship-sites")
def list_sites():
    require_role(ALL_ROLES)
    status = request.args.get("status")
    items = sorted_collection(
        store.externship_sites,
        predicate=(lambda e: e["status"] == status) if status else None)
    page, meta = paginate(items)
    return success([serialize(e) for e in page], 200, pagination=meta)


@bp.get("/v1/externship-sites/<sid>")
def get_site(sid):
    require_role(ALL_ROLES)
    site = find_or_404(store.externship_sites, sid, "ExternshipSite")
    return success(serialize(site), 200)


@bp.post("/v1/externship-sites/<sid>/suspend")
def suspend_site(sid):
    require_role(["AcademicAdvisor", "SystemAdmin"])
    site = find_or_404(store.externship_sites, sid, "ExternshipSite")
    if site["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Site must be ACTIVE to suspend.")
    site["status"] = "SUSPENDED"
    bump(site)
    return success(serialize(site), 200)
