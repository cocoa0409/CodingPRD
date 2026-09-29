"""Course sections, assignments and the qualification verdict (PRD 3.4)."""

from flask import Blueprint

import db
import guards
import middleware
import response
import serialize
import util
import validate
from constants import (
    ASSIGNMENT_ROLES, ASSIGNMENT_STATUSES, COURSE_LEVELS, CREDENTIAL_ANALYST,
    DELIVERY_MODES, EXCEPTION_CODES, INACTIVE_ASSIGNMENT_STATUSES,
    MAX_TERM_CREDIT_HOURS, MEETING_DAYS, PROGRAM_DEAN, QUALIFICATION_BASES,
    READ_ROLES, REMEDIATION_ACTIONS,
)
from db import store, touch
from errors import ApiError
from routes.common import list_response, match
from services import calc, domain, lookup

bp = Blueprint("sections", __name__)


# --------------------------------------------------------------- course sections
@bp.route("/course-sections", methods=["POST"])
def create_section():
    middleware.require_role(PROGRAM_DEAN)
    payload = validate.body()

    raw_program_id = payload.get("program_id")
    if isinstance(raw_program_id, str):
        middleware.require_dean_owns(raw_program_id)

    course_code = validate.req_str(payload, "course_code")
    title = validate.req_str(payload, "title")
    program_id = validate.req_str(payload, "program_id")
    term_id = validate.req_str(payload, "term_id")
    discipline_id = validate.req_str(payload, "discipline_id")
    course_level = validate.req_enum(payload, "course_level", COURSE_LEVELS)
    credit_hours = validate.req_num(payload, "credit_hours", exclusive_min=0)
    delivery_mode = validate.req_enum(payload, "delivery_mode", DELIVERY_MODES)

    building_code = validate.opt_str(payload, "building_code", allow_empty=False)
    meeting_days = validate.req_str_array(payload, "meeting_days", allowed=MEETING_DAYS,
                                          allow_absent=True, default=[])
    start_minute = validate.opt_int(payload, "meeting_start_minute", minimum=0, maximum=1440)
    end_minute = validate.opt_int(payload, "meeting_end_minute", minimum=0, maximum=1440)

    if delivery_mode == "ONLINE_ASYNC":
        if meeting_days:
            validate.bad("Field 'meeting_days' must be empty for ONLINE_ASYNC delivery.")
    else:
        if building_code is None:
            validate.bad("Field 'building_code' is required unless delivery_mode is "
                         "ONLINE_ASYNC.")
        if start_minute is None:
            validate.bad("Field 'meeting_start_minute' is required unless delivery_mode "
                         "is ONLINE_ASYNC.")
        if end_minute is None:
            validate.bad("Field 'meeting_end_minute' is required unless delivery_mode "
                         "is ONLINE_ASYNC.")

    lookup.program(program_id)
    term = lookup.term(term_id)
    lookup.discipline(discipline_id)

    guards.require_term_status(term, ("PLANNING", "OPEN"))

    if start_minute is not None and end_minute is not None:
        if start_minute >= end_minute:
            raise ApiError("ERR_INVALID_WINDOW",
                           "meeting_start_minute must be before meeting_end_minute.")

    row = db.new_row(
        course_code=course_code,
        title=title,
        program_id=program_id,
        term_id=term_id,
        discipline_id=discipline_id,
        course_level=course_level,
        credit_hours=credit_hours,
        delivery_mode=delivery_mode,
        building_code=building_code,
        meeting_days=meeting_days,
        meeting_start_minute=start_minute,
        meeting_end_minute=end_minute,
        instructor_of_record_id=None,
    )
    store.course_sections[row["id"]] = row
    return response.created(serialize.section(row))


@bp.route("/course-sections/<section_id>", methods=["GET"])
def read_section(section_id):
    middleware.require_role(*READ_ROLES)
    return response.ok(serialize.section(lookup.section(section_id)))


@bp.route("/course-sections", methods=["GET"])
def list_sections():
    middleware.require_role(*READ_ROLES)
    program_id = validate.q_str("program_id")
    term_id = validate.q_str("term_id")
    discipline_id = validate.q_str("discipline_id")
    instructor_of_record_id = validate.q_str("instructor_of_record_id")
    course_level = validate.q_enum("course_level", COURSE_LEVELS)
    delivery_mode = validate.q_enum("delivery_mode", DELIVERY_MODES)
    rows = [r for r in db.ordered(store.course_sections)
            if match(r, "program_id", program_id)
            and match(r, "term_id", term_id)
            and match(r, "discipline_id", discipline_id)
            and match(r, "instructor_of_record_id", instructor_of_record_id)
            and match(r, "course_level", course_level)
            and match(r, "delivery_mode", delivery_mode)]
    return list_response(rows, serialize.section)


# ------------------------------------------------------------ course assignments
def _reconcile(program_id, term_id, delta=0, recompute_roster=True):
    """Push an assignment change up through the program and covering roster."""
    program = store.programs.get(program_id)
    if delta:
        domain.bump_unqualified(program, delta)
    if not recompute_roster:
        return
    roster = lookup.generated_roster(program_id, term_id)
    if roster is None:
        return
    domain.recompute_roster(roster)
    if program is not None:
        domain.write_program_adequacy(program, term_id)


@bp.route("/course-assignments", methods=["POST"])
def create_assignment():
    middleware.require_role(PROGRAM_DEAN)
    payload = validate.body()

    provisional = lookup.maybe("course_sections", payload.get("course_section_id"))
    if provisional is not None:
        middleware.require_dean_owns(provisional.get("program_id"))

    section_id = validate.req_str(payload, "course_section_id")
    faculty_id = validate.req_str(payload, "faculty_member_id")
    assignment_role = validate.req_enum(payload, "assignment_role", ASSIGNMENT_ROLES)
    expected_version = validate.req_int(payload, "expected_section_version")

    section = lookup.section(section_id)
    faculty = lookup.faculty(faculty_id)

    if expected_version != section["version"]:
        raise ApiError("ERR_STALE_SECTION_VERSION")

    program_id = section["program_id"]
    term_id = section["term_id"]
    term = store.terms.get(term_id)

    guards.require_term_status(term, ("OPEN", "ROSTER_LOCKED"))
    guards.require_roster_not_certified(program_id, term_id)
    guards.require_no_review_lockout(program_id)
    guards.require_not_separated(faculty)
    guards.require_appointable(faculty)

    for existing in lookup.assignments_of_section(section_id):
        if (existing["faculty_member_id"] == faculty_id
                and existing["status"] not in INACTIVE_ASSIGNMENT_STATUSES):
            raise ApiError("ERR_DUPLICATE_ASSIGNMENT")

    for other in lookup.assignments_of_faculty(faculty_id):
        if other["status"] in INACTIVE_ASSIGNMENT_STATUSES:
            continue
        other_section = store.course_sections.get(other["course_section_id"])
        if not other_section or other_section["term_id"] != term_id:
            continue
        if other_section["id"] == section["id"]:
            continue
        if calc.blocks_conflict(section, other_section):
            raise ApiError("ERR_TEACHING_BLOCK_CONFLICT")

    ceiling = MAX_TERM_CREDIT_HOURS.get(faculty["employment_class"])
    if ceiling is not None:
        current_load = calc.term_load(faculty_id, term_id)
        if current_load + util.dec(section["credit_hours"]) > util.dec(ceiling):
            raise ApiError("ERR_TERM_LOAD_EXCEEDED")

    row = db.new_row(
        course_section_id=section_id,
        faculty_member_id=faculty_id,
        assignment_role=assignment_role,
        status="PENDING_VERIFICATION",
        qualification_basis="NONE",
        exception_code=None,
        alignment_score=None,
        remediation_action=None,
        superseded_by_assignment_id=None,
    )
    store.course_assignments[row["id"]] = row

    domain.apply_decision(row)
    delta = domain.unqualified_delta("", row["status"])

    incumbent = None
    if assignment_role == "INSTRUCTOR_OF_RECORD":
        for other in lookup.assignments_of_section(section_id):
            if other["id"] == row["id"]:
                continue
            if other["assignment_role"] != "INSTRUCTOR_OF_RECORD":
                continue
            if other["status"] in INACTIVE_ASSIGNMENT_STATUSES:
                continue
            incumbent = other
            break
        section["instructor_of_record_id"] = faculty_id

    if incumbent is not None:
        incumbent_status = incumbent["status"]
        incumbent["status"] = "SUPERSEDED"
        incumbent["superseded_by_assignment_id"] = row["id"]
        incumbent["remediation_action"] = None
        touch(incumbent)
        delta += domain.unqualified_delta(incumbent_status, "SUPERSEDED")
        incumbent_faculty = store.faculty_members.get(incumbent["faculty_member_id"])
        if incumbent_faculty is not None:
            domain.sync_faculty_load(incumbent_faculty)
        if incumbent_status == "REMEDIATION_IN_PROGRESS":
            domain.withdraw_backing_justifications(incumbent)

    touch(section)
    domain.sync_faculty_load(faculty)
    # PRD 2.11: the new assignment enters the covering roster's included set, so the
    # roster snapshot and the program's adequacy reconcile inside this same request.
    _reconcile(program_id, term_id, delta=delta)

    return response.created(serialize.assignment(row))


@bp.route("/course-assignments/<assignment_id>", methods=["GET"])
def read_assignment(assignment_id):
    middleware.require_role(*READ_ROLES)
    return response.ok(serialize.assignment(lookup.assignment(assignment_id)))


@bp.route("/course-assignments", methods=["GET"])
def list_assignments():
    middleware.require_role(*READ_ROLES)
    section_id = validate.q_str("course_section_id")
    faculty_id = validate.q_str("faculty_member_id")
    superseded_by = validate.q_str("superseded_by_assignment_id")
    status = validate.q_enum("status", ASSIGNMENT_STATUSES)
    exception_code = validate.q_enum("exception_code", EXCEPTION_CODES)
    basis = validate.q_enum("qualification_basis", QUALIFICATION_BASES)
    rows = [r for r in db.ordered(store.course_assignments)
            if match(r, "course_section_id", section_id)
            and match(r, "faculty_member_id", faculty_id)
            and match(r, "superseded_by_assignment_id", superseded_by)
            and match(r, "status", status)
            and match(r, "exception_code", exception_code)
            and match(r, "qualification_basis", basis)]
    return list_response(rows, serialize.assignment)


@bp.route("/course-sections/<section_id>/course-assignments", methods=["GET"])
def list_section_assignments(section_id):
    middleware.require_role(*READ_ROLES)
    lookup.section(section_id)
    status = validate.q_enum("status", ASSIGNMENT_STATUSES)
    rows = [r for r in lookup.assignments_of_section(section_id)
            if match(r, "status", status)]
    return list_response(rows, serialize.assignment)


def _assignment_context(assignment_id, dean_ownership):
    provisional = lookup.maybe("course_assignments", assignment_id)
    if dean_ownership and provisional is not None:
        section = store.course_sections.get(provisional["course_section_id"])
        if section is not None:
            middleware.require_dean_owns(section.get("program_id"))
    return provisional


@bp.route("/course-assignments/<assignment_id>/remediation", methods=["POST"])
def open_remediation(assignment_id):
    middleware.require_role(PROGRAM_DEAN)
    _assignment_context(assignment_id, True)
    payload = validate.body()
    action = validate.req_enum(payload, "remediation_action", REMEDIATION_ACTIONS)
    validate.opt_str(payload, "note")

    assignment = lookup.assignment(assignment_id)
    section = store.course_sections[assignment["course_section_id"]]

    if assignment["status"] != "EXCEPTION_FLAGGED":
        guards.invalid_state("An assignment in %s may not enter remediation."
                             % assignment["status"])

    term = store.terms.get(section["term_id"])
    guards.require_term_status(term, ("OPEN", "ROSTER_LOCKED"))
    guards.require_roster_not_certified(section["program_id"], section["term_id"])

    assignment["status"] = "REMEDIATION_IN_PROGRESS"
    assignment["remediation_action"] = action
    touch(assignment)

    roster = lookup.generated_roster(section["program_id"], section["term_id"])
    if roster is not None:
        domain.recompute_roster(roster)

    return response.ok(serialize.assignment(assignment))


@bp.route("/course-assignments/<assignment_id>/reverification", methods=["POST"])
def reverify_assignment(assignment_id):
    middleware.require_role(CREDENTIAL_ANALYST)
    validate.body()

    assignment = lookup.assignment(assignment_id)
    section = store.course_sections[assignment["course_section_id"]]

    if assignment["status"] != "REMEDIATION_IN_PROGRESS":
        guards.invalid_state("An assignment in %s may not be re-verified."
                             % assignment["status"])

    term = store.terms.get(section["term_id"])
    guards.require_term_status(term, ("OPEN", "ROSTER_LOCKED"))
    guards.require_roster_not_certified(section["program_id"], section["term_id"])

    old_status, new_status, _changed = domain.apply_decision(assignment)
    assignment["remediation_action"] = None
    touch(assignment)

    _reconcile(section["program_id"], section["term_id"],
               delta=domain.unqualified_delta(old_status, new_status))

    return response.ok(serialize.assignment(assignment))


@bp.route("/course-assignments/<assignment_id>/withdrawal", methods=["POST"])
def withdraw_assignment(assignment_id):
    middleware.require_role(PROGRAM_DEAN)
    _assignment_context(assignment_id, True)
    payload = validate.body()
    validate.opt_str(payload, "reason")

    assignment = lookup.assignment(assignment_id)
    section = store.course_sections[assignment["course_section_id"]]

    old_status = assignment["status"]
    if old_status not in domain.ACTIVE_ASSIGNMENT_STATUSES:
        guards.invalid_state("An assignment in %s may not be withdrawn." % old_status)

    term = store.terms.get(section["term_id"])
    guards.require_term_status(term, ("OPEN", "ROSTER_LOCKED"))
    guards.require_roster_not_certified(section["program_id"], section["term_id"])
    guards.require_no_review_lockout(section["program_id"])

    assignment["status"] = "WITHDRAWN"
    assignment["remediation_action"] = None
    touch(assignment)

    if old_status == "REMEDIATION_IN_PROGRESS":
        domain.withdraw_backing_justifications(assignment)

    if (assignment["assignment_role"] == "INSTRUCTOR_OF_RECORD"
            and section.get("instructor_of_record_id") == assignment["faculty_member_id"]):
        section["instructor_of_record_id"] = None
        touch(section)

    faculty = store.faculty_members.get(assignment["faculty_member_id"])
    if faculty is not None:
        domain.sync_faculty_load(faculty)

    _reconcile(section["program_id"], section["term_id"],
               delta=domain.unqualified_delta(old_status, "WITHDRAWN"),
               recompute_roster=(old_status != "PENDING_VERIFICATION"))

    return response.ok(serialize.assignment(assignment))
