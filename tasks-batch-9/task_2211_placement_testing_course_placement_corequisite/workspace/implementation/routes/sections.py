"""Sections: planning, corequisite pairing and the status axis."""

from flask import Blueprint

from constants import PAIR_ROLES, PAIRING_STATES, REGISTRATION_STATES, SECTION_STATUSES
from db import base_row, db, touch
from errors import fail
from middleware import authenticate
from response import created, ok
from routes.common import eq, filter_rows, find, listing
from services import cascades, serialize
from validators import Field, parse_body, parse_query

bp = Blueprint("sections", __name__)

READERS = ("SystemAdmin", "Registrar", "AssessmentStaff", "Instructor", "Student")

CREATE_SPEC = {
    "course_id": Field("id", required=True),
    "term_code": Field("str", required=True, min_len=5, max_len=10),
    "room_code": Field("str", required=True),
    "meets_start_at": Field("datetime", required=True),
    "meets_end_at": Field("datetime", required=True),
    "seat_capacity": Field("int", required=True, minimum=1, maximum=300),
}

LIST_SPEC = {
    "course_id": Field("id"),
    "term_code": Field("str"),
    "room_code": Field("str"),
    "status": Field("enum", values=SECTION_STATUSES),
    "pairing_state": Field("enum", values=PAIRING_STATES),
    "role_in_pair": Field("enum", values=PAIR_ROLES),
    "linked_section_id": Field("id"),
}

PAIR_SPEC = {"support_section_id": Field("id", required=True)}
STATUS_SPEC = {"target_status": Field("enum", required=True, values=SECTION_STATUSES)}
REGISTRATION_LIST_SPEC = {"state": Field("enum", values=REGISTRATION_STATES)}


@bp.post("/sections")
def create_section():
    authenticate(("SystemAdmin", "Registrar"))
    body = parse_body(CREATE_SPEC)

    if not (body["meets_end_at"] > body["meets_start_at"]):
        fail("ERR_INVALID_REQUEST", "meets_end_at must be strictly after meets_start_at")

    course = find("courses", body["course_id"])
    if course["status"] != "ACTIVE":
        fail("ERR_COURSE_RETIRED", "a section may not be planned against a retired course")

    row = base_row()
    row.update({
        "course_id": course["id"],
        "term_code": body["term_code"],
        "room_code": body["room_code"],
        "meets_start_at": body["meets_start_at"],
        "meets_end_at": body["meets_end_at"],
        "seat_capacity": body["seat_capacity"],
        "linked_section_id": None,
        "role_in_pair": "NONE",
        "pairing_state": "UNPAIRED",
        "status": "PLANNED",
    })
    db.sections[row["id"]] = row
    return created(serialize.section(row))


@bp.get("/sections/<section_id>")
def get_section(section_id):
    authenticate(READERS)
    parse_query({}, paginated=False)
    row = find("sections", section_id)
    return ok(serialize.section(row))


@bp.get("/sections")
def list_sections():
    authenticate(READERS)
    query = parse_query(LIST_SPEC)
    rows = filter_rows(list(db.sections.values()), query, {
        "course_id": eq("course_id"),
        "term_code": eq("term_code"),
        "room_code": eq("room_code"),
        "status": eq("status"),
        "pairing_state": eq("pairing_state"),
        "role_in_pair": eq("role_in_pair"),
        "linked_section_id": eq("linked_section_id"),
    })
    return listing(rows, query, serialize.section)


@bp.post("/sections/<section_id>/pair")
def pair(section_id):
    authenticate(("Registrar",))
    body = parse_body(PAIR_SPEC)
    primary = find("sections", section_id)
    support = find("sections", body["support_section_id"])

    if primary["pairing_state"] not in ("UNPAIRED", "PAIR_BROKEN"):
        fail("ERR_INVALID_STATE", "the primary section is already PAIRED")
    if primary["status"] != "PLANNED" or support["status"] != "PLANNED":
        fail("ERR_INVALID_STATE", "both sections must be in status PLANNED")

    primary_course = db.courses.get(primary["course_id"])
    support_course = db.courses.get(support["course_id"])
    mismatch = (
        primary_course is None
        or support_course is None
        or primary_course["is_support_course"]
        or not support_course["is_support_course"]
        or primary["term_code"] != support["term_code"]
        or support["pairing_state"] != "UNPAIRED"
    )
    if not mismatch:
        joined = any(
            edge["status"] == "ACTIVE"
            and edge["requisite_type"] == "COREQUISITE"
            and edge["course_id"] == primary_course["id"]
            and edge["requisite_course_id"] == support_course["id"]
            for edge in db.requisites.values()
        )
        mismatch = not joined
    if mismatch:
        fail("ERR_COREQ_SECTION_MISMATCH", "the two sections may not form a corequisite pair")

    if (
        primary["meets_start_at"] < support["meets_end_at"]
        and support["meets_start_at"] < primary["meets_end_at"]
    ):
        fail("ERR_COREQ_TIME_CONFLICT", "the two meeting blocks overlap")

    primary["pairing_state"] = "PAIRED"
    primary["role_in_pair"] = "PRIMARY"
    primary["linked_section_id"] = support["id"]
    support["pairing_state"] = "PAIRED"
    support["role_in_pair"] = "SUPPORT"
    support["linked_section_id"] = primary["id"]
    touch(primary)
    touch(support)
    return ok(serialize.section(primary))


@bp.post("/sections/<section_id>/unpair")
def unpair(section_id):
    authenticate(("Registrar",))
    parse_body({})
    primary = find("sections", section_id)

    if primary["pairing_state"] != "PAIRED":
        fail("ERR_INVALID_STATE", "only a PAIRED section may be unpaired")
    if primary["role_in_pair"] != "PRIMARY":
        fail("ERR_COREQ_SECTION_MISMATCH", "only the PRIMARY half may dissolve a pair")
    if primary["status"] not in ("PLANNED", "OPEN"):
        fail("ERR_INVALID_STATE", "the section's status must be PLANNED or OPEN")

    support = db.sections.get(primary["linked_section_id"])
    if support is not None:
        for reg in db.registrations.values():
            if (
                reg["section_id"] == support["id"]
                and reg["coreq_registration_id"] is not None
                and reg["state"] in ("PENDING", "ENROLLED", "WAITLISTED")
            ):
                fail("ERR_INVALID_STATE", "companion registrations must be dropped first")

    primary["pairing_state"] = "UNPAIRED"
    primary["role_in_pair"] = "NONE"
    primary["linked_section_id"] = None
    touch(primary)
    if support is not None:
        support["pairing_state"] = "UNPAIRED"
        support["role_in_pair"] = "NONE"
        support["linked_section_id"] = None
        touch(support)
    return ok(serialize.section(primary))


@bp.post("/sections/<section_id>/status")
def set_status(section_id):
    authenticate(("Registrar", "SystemAdmin"))
    body = parse_body(STATUS_SPEC)
    row = find("sections", section_id)

    target = body["target_status"]
    current = row["status"]

    if target == "OPEN":
        if current not in ("PLANNED", "CLOSED"):
            fail("ERR_SECTION_NOT_CLOSED", "%s -> OPEN is not a declared transition" % current)
    elif target == "CLOSED":
        if current != "OPEN":
            fail("ERR_INVALID_STATE", "%s -> CLOSED is not a declared transition" % current)
    elif target == "CANCELLED":
        if current not in ("PLANNED", "OPEN", "CLOSED"):
            fail("ERR_INVALID_STATE", "%s -> CANCELLED is not a declared transition" % current)
    else:
        fail("ERR_INVALID_STATE", "%s -> %s is not a declared transition" % (current, target))

    if target == "OPEN":
        course = db.courses.get(row["course_id"])
        if course is None or course["status"] != "ACTIVE":
            fail("ERR_COURSE_RETIRED", "the section's course is retired")
        if not course["is_support_course"] and row["pairing_state"] != "PAIRED":
            needs_pair = any(
                rule["status"] == "ACTIVE"
                and rule["target_course_id"] == course["id"]
                and rule["coreq_required"]
                for rule in db.rules.values()
            )
            if needs_pair:
                fail("ERR_COREQ_PAIRING_REQUIRED", "the section must be PAIRED before it opens")

    if target == "CANCELLED":
        cascades.cancel_section(row)
        return ok(serialize.section(row))

    row["status"] = target
    touch(row)
    return ok(serialize.section(row))


@bp.get("/sections/<section_id>/registrations")
def list_section_registrations(section_id):
    authenticate(("SystemAdmin", "Registrar", "Instructor"))
    query = parse_query(REGISTRATION_LIST_SPEC)
    row = find("sections", section_id)
    rows = [r for r in db.registrations.values() if r["section_id"] == row["id"]]
    rows = filter_rows(rows, query, {"state": eq("state")})
    return listing(rows, query, serialize.registration)
