"""CourseSection endpoints (PRD §3.3, §3.6): create, lifecycle transitions
with the late-cancel cascade, and registrar enrollment-sync (OCC)."""

import db
from errors import (
    ApiError,
    ERR_SECTION_NOT_FOUND,
    ERR_TERM_NOT_FOUND,
    ERR_COURSE_NOT_FOUND,
    ERR_VALIDATION,
    ERR_INVALID_TIME_RANGE,
    ERR_INVALID_TERM_STATE,
    ERR_INVALID_SECTION_TRANSITION,
    ERR_DEAN_OVERRIDE_REQUIRED,
    ERR_DUPLICATE_SECTION,
    ERR_MODALITY_NOT_ALLOWED,
    ERR_ENROLLMENT_EXCEEDS_CAP,
    ERR_STALE_VERSION,
    ERR_COMP_BUDGET_EXCEEDED,
)
from middleware import authenticate, ALL_ROLES, CHAIR, REGISTRAR
from response import success_obj, success_list
from routes import make_blueprint
from util import body_json, check_shape, present, pagination_params, paginate, apply_filters
import services

bp = make_blueprint("sections")

SECTION_STATUSES = ["PROPOSED", "SCHEDULED", "STAFFED", "CANCELLED"]
MODALITIES = ["IN_PERSON", "ONLINE", "HYBRID"]
MEETING_DAYS = ["MON", "TUE", "WED", "THU", "FRI"]


def require_section(section_id):
    section = db.get("course_sections", section_id)
    if section is None:
        raise ApiError(ERR_SECTION_NOT_FOUND, 404, "section not found")
    return section


@bp.post("/course-sections")
def create_section():
    authenticate([CHAIR])
    body = body_json()
    check_shape(body, {
        "term_id": {"type": "string", "required": True},
        "course_id": {"type": "string", "required": True},
        "section_number": {"type": "string", "required": True},
        "modality": {"type": "enum", "values": MODALITIES, "required": True},
        "meeting_day": {"type": "enum", "values": MEETING_DAYS, "required": True},
        "start_minute": {"type": "integer", "required": True},
        "end_minute": {"type": "integer", "required": True},
        "enrollment_cap": {"type": "integer"},
    })
    # Shape (priority 3): the meeting window failures are ERR_INVALID_TIME_RANGE.
    start_minute = body["start_minute"]
    end_minute = body["end_minute"]
    if not (0 <= start_minute <= 1439) or not (0 <= end_minute <= 1439) or end_minute <= start_minute:
        raise ApiError(ERR_INVALID_TIME_RANGE, 400,
                       "minutes must be within 0..1439 and end_minute must be > start_minute")
    # Existence (priority 4), body FKs in declared input order.
    term = db.get("workload_terms", body["term_id"])
    if term is None:
        raise ApiError(ERR_TERM_NOT_FOUND, 404, "term not found")
    course = db.get("courses", body["course_id"])
    if course is None:
        raise ApiError(ERR_COURSE_NOT_FOUND, 404, "course not found")
    # State (priority 5): sections are creatable only while DRAFT or OPEN.
    if term["status"] not in ("DRAFT", "OPEN"):
        raise ApiError(ERR_INVALID_TERM_STATE, 409,
                       "sections may be created only while the term is DRAFT or OPEN")
    # Business constraints (priority 8).
    for s in db.all_of("course_sections"):
        if (s["term_id"] == body["term_id"] and s["course_id"] == body["course_id"]
                and s["section_number"] == body["section_number"]):
            raise ApiError(ERR_DUPLICATE_SECTION, 409,
                           "section_number already used for this term and course")
    if body["modality"] not in course["allowed_modalities"]:
        raise ApiError(ERR_MODALITY_NOT_ALLOWED, 422,
                       "modality is not in the course's allowed_modalities")
    section = db.new_entity("course_sections", {
        "term_id": body["term_id"],
        "course_id": body["course_id"],
        "section_number": body["section_number"],
        "modality": body["modality"],
        "meeting_day": body["meeting_day"],
        "start_minute": start_minute,
        "end_minute": end_minute,
        "enrollment_cap": body["enrollment_cap"] if present(body, "enrollment_cap")
                          else course["default_enrollment_cap"],
        "enrolled_count": 0,
        "is_late_cancelled": False,
        "status": "PROPOSED",
    })
    return success_obj(db.public(section), 201)


@bp.get("/course-sections")
def list_sections():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("course_sections"), ["term_id", "course_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(s) for s in page], limit, offset, total, has_more)


@bp.get("/course-sections/<sectionId>")
def get_section(sectionId):
    authenticate(ALL_ROLES)
    return success_obj(db.public(require_section(sectionId)), 200)


@bp.post("/course-sections/<sectionId>/transition")
def transition_section(sectionId):
    authenticate([CHAIR])
    body = body_json()
    check_shape(body, {
        "to_state": {"type": "enum", "values": SECTION_STATUSES, "required": True},
        "dean_override": {"type": "boolean"},
    })
    section = require_section(sectionId)
    term = services.term_of_section(section)
    to_state = body["to_state"]
    from_state = section["status"]
    if to_state == "SCHEDULED":
        if from_state != "PROPOSED":
            raise ApiError(ERR_INVALID_SECTION_TRANSITION, 409,
                           f"cannot move a {from_state} section to SCHEDULED")
        if term["status"] not in ("DRAFT", "OPEN"):
            raise ApiError(ERR_INVALID_TERM_STATE, 409,
                           "sections may be scheduled only while the term is DRAFT or OPEN")
        section["status"] = "SCHEDULED"
        db.touch(section)
        return success_obj(db.public(section), 200)
    if to_state == "CANCELLED":
        if from_state not in ("PROPOSED", "SCHEDULED", "STAFFED"):
            raise ApiError(ERR_INVALID_SECTION_TRANSITION, 409,
                           f"cannot move a {from_state} section to CANCELLED")
        if term["status"] == "PUBLISHED" and body.get("dean_override") is not True:
            raise ApiError(ERR_DEAN_OVERRIDE_REQUIRED, 409,
                           "cancelling a section in a PUBLISHED term requires dean_override=true")
        late = services.is_late(term)
        if from_state == "STAFFED" and late:
            confirmed = [a for a in db.all_of("assignments")
                         if a["section_id"] == section["id"] and a["status"] == "CONFIRMED"]
            if confirmed:
                needed = term["late_cancel_stipend_cents"] * len(confirmed)
                if term["comp_budget_spent_cents"] + needed > term["comp_budget_cents"]:
                    raise ApiError(ERR_COMP_BUDGET_EXCEEDED, 402,
                                   "late-cancel stipends would exceed the term compensation budget")
        if from_state in ("SCHEDULED", "STAFFED"):
            section["is_late_cancelled"] = late
        services.cancel_section_cascade(section, term, late)
        return success_obj(db.public(section), 200)
    # PROPOSED / STAFFED are not chair-reachable targets.
    raise ApiError(ERR_INVALID_SECTION_TRANSITION, 409,
                   f"cannot move a {from_state} section to {to_state}")


@bp.post("/course-sections/<sectionId>/enrollment-sync")
def enrollment_sync(sectionId):
    authenticate([REGISTRAR])
    body = body_json()
    check_shape(body, {
        "enrolled_count": {"type": "integer", "min": 0, "required": True},
        "expected_section_version": {"type": "integer", "required": True},
    })
    section = require_section(sectionId)
    # OCC (priority 5.1) before the capacity business rule (priority 8).
    if body["expected_section_version"] != section["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_section_version does not match the section's current version")
    if body["enrolled_count"] > section["enrollment_cap"]:
        raise ApiError(ERR_ENROLLMENT_EXCEEDS_CAP, 422, "enrolled_count exceeds enrollment_cap")
    section["enrolled_count"] = body["enrolled_count"]
    db.touch(section)
    return success_obj(db.public(section), 200)
