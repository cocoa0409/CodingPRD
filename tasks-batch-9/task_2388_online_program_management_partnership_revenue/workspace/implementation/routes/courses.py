"""Course reads, design-metadata amendment and the design lifecycle."""

from flask import Blueprint, request

import constants as C
import db
import serializers
from db import store, touch
from errors import ApiError, bad_request
from middleware import PARTNER, authenticate, body, check_action_role, check_scope
from response import object_response
from routes.common import get_course, get_program, listing
from routes.programs import check_prerequisite_cycle, resolve_prerequisite
from validation import Field, enum_filter, pagination_args, validate_body

bp = Blueprint("courses", __name__)

READ_ROLES = ("PlatformAdmin", "UniversityProvost", "FacultyChair", "ComplianceAuditor",
              "PartnerAccountLead")

PATCH_SPEC = {
    "title": Field("string"),
    "credits": Field("integer", minimum=0),
    "design_cost_cents": Field("integer"),
    "required_for_launch": Field("boolean"),
    "prerequisite_course_id": Field("string", nullable=True),
    "ip_license_grant_back": Field("boolean"),
}

ACTION_SPEC = {
    "action": Field("enum", required=True, enum=tuple(C.DESIGN_ACTION_ROLES)),
    "revision_note": Field("string"),
    "faculty_approver_name": Field("string"),
}

TRANSITIONS = {
    "START_DESIGN": (("NOT_STARTED",), "IN_DESIGN"),
    "SUBMIT_FOR_FACULTY_REVIEW": (("IN_DESIGN",), "FACULTY_REVIEW"),
    "REQUEST_REVISION": (("FACULTY_REVIEW",), "IN_DESIGN"),
    "APPROVE": (("FACULTY_REVIEW",), "APPROVED"),
    "RETIRE": (("APPROVED",), "RETIRED"),
}

START_DESIGN_PROGRAM_STATES = ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED",
                               "LAUNCHED")


def _partnership_id_of(course):
    program = store.programs.get(course["program_id"])
    return program["partnership_id"] if program else None


@bp.get("/courses/<course_id>")
def read(course_id):
    uid, role = authenticate(READ_ROLES)
    course = get_course(course_id)
    check_scope(role, uid, _partnership_id_of(course))
    return object_response(serializers.course(course))


@bp.get("/courses")
def index():
    uid, role = authenticate(READ_ROLES)
    limit, offset = pagination_args(request.args)
    design_status = enum_filter(request.args, "design_status", C.DESIGN_STATUSES)
    program_id = request.args.get("program_id")
    prerequisite_id = request.args.get("prerequisite_course_id")

    if role == PARTNER and program_id is not None:
        program = store.programs.get(program_id)
        if program is not None and program["partnership_id"] != uid:
            raise ApiError("ERR_PARTNERSHIP_SCOPE_VIOLATION")

    items = db.sort_created(list(store.courses.values()))
    if program_id is not None:
        items = [c for c in items if c["program_id"] == program_id]
    if prerequisite_id is not None:
        items = [c for c in items if c["prerequisite_course_id"] == prerequisite_id]
    if design_status is not None:
        items = [c for c in items if c["design_status"] == design_status]
    if role == PARTNER:
        items = [c for c in items if _partnership_id_of(c) == uid]
    return listing(items, serializers.course, limit, offset)


@bp.patch("/courses/<course_id>")
def amend(course_id):
    uid, role = authenticate(("PartnerAccountLead", "FacultyChair"))
    values = validate_body(body(), PATCH_SPEC)
    course = get_course(course_id)

    prerequisite_supplied = "prerequisite_course_id" in values
    prerequisite_id = values.get("prerequisite_course_id")
    if prerequisite_supplied and prerequisite_id is not None:
        resolve_prerequisite(course["program_id"], prerequisite_id)

    check_scope(role, uid, _partnership_id_of(course))

    if course["design_status"] not in ("NOT_STARTED", "IN_DESIGN", "DESIGN_SUSPENDED"):
        raise ApiError("ERR_COURSE_INVALID_DESIGN_STATE")

    if prerequisite_supplied:
        check_prerequisite_cycle(course["program_id"], course["id"], prerequisite_id)

    for name in ("title", "credits", "design_cost_cents", "required_for_launch",
                 "ip_license_grant_back"):
        if name in values:
            course[name] = values[name]
    if prerequisite_supplied:
        course["prerequisite_course_id"] = prerequisite_id

    touch(course)
    return object_response(serializers.course(course))


@bp.post("/courses/<course_id>/design-actions")
def design_action(course_id):
    uid, role = authenticate(("PartnerAccountLead", "FacultyChair"))
    values = validate_body(body(), ACTION_SPEC)
    action = values["action"]
    check_action_role(role, action, C.DESIGN_ACTION_ROLES)

    if action == "APPROVE" and not values.get("faculty_approver_name"):
        raise bad_request("faculty_approver_name is required on APPROVE.")

    course = get_course(course_id)
    check_scope(role, uid, _partnership_id_of(course))

    sources, target = TRANSITIONS[action]
    if course["design_status"] not in sources:
        raise ApiError("ERR_COURSE_INVALID_DESIGN_STATE")

    program = get_program(course["program_id"])

    if action == "START_DESIGN":
        if program["status"] not in START_DESIGN_PROGRAM_STATES:
            raise ApiError("ERR_COURSE_INVALID_DESIGN_STATE")
    elif action == "SUBMIT_FOR_FACULTY_REVIEW":
        prerequisite_id = course.get("prerequisite_course_id")
        if prerequisite_id is not None:
            prerequisite = store.courses.get(prerequisite_id)
            if (prerequisite is None
                    or prerequisite["design_status"] not in ("FACULTY_REVIEW", "APPROVED")):
                raise ApiError("ERR_COURSE_INVALID_DESIGN_STATE")
    elif action == "RETIRE":
        for other in db.courses_of(program["id"]):
            if (other["prerequisite_course_id"] == course["id"]
                    and other["design_status"] in ("NOT_STARTED", "IN_DESIGN",
                                                   "FACULTY_REVIEW")):
                raise ApiError("ERR_COURSE_INVALID_DESIGN_STATE")

    if action == "APPROVE":
        if not (course["content_owner"] == "UNIVERSITY"
                or course["ip_license_grant_back"] is True):
            raise ApiError("ERR_FACULTY_IP_OWNERSHIP_VIOLATION")
        course["faculty_approver_name"] = values["faculty_approver_name"]
    elif action == "REQUEST_REVISION":
        course["revision_round"] += 1

    course["design_status"] = target
    touch(course)
    return object_response(serializers.course(course))
