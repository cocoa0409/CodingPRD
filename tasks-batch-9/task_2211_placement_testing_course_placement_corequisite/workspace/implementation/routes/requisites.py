"""Requisite edges: the prerequisite / corequisite / advisory graph."""

from flask import Blueprint

from constants import COURSE_STATUSES, ENFORCEMENTS, MIN_GRADES, REQUISITE_TYPES
from db import base_row, db, sort_rows
from errors import fail
from middleware import authenticate
from response import created, ok
from routes.common import eq, filter_rows, find, listing
from services import calc, cascades, serialize
from validators import Field, parse_body, parse_query

bp = Blueprint("requisites", __name__)

READERS = ("SystemAdmin", "AssessmentStaff", "Registrar", "Instructor", "Student")

CREATE_SPEC = {
    "course_id": Field("id", required=True),
    "requisite_course_id": Field("id", required=True),
    "requisite_type": Field("enum", required=True, values=REQUISITE_TYPES),
    "min_grade": Field("enum", values=MIN_GRADES),
    "enforcement": Field("enum", values=ENFORCEMENTS),
}

LIST_SPEC = {
    "course_id": Field("id"),
    "requisite_course_id": Field("id"),
    "requisite_type": Field("enum", values=REQUISITE_TYPES),
    "enforcement": Field("enum", values=ENFORCEMENTS),
    "status": Field("enum", values=COURSE_STATUSES),
}


@bp.post("/course-requisites")
def create_requisite():
    authenticate(("SystemAdmin",))
    body = parse_body(CREATE_SPEC)

    course = find("courses", body["course_id"])
    requisite_course = find("courses", body["requisite_course_id"])

    if body["requisite_type"] == "PREREQUISITE":
        if calc.creates_cycle(course["id"], requisite_course["id"]):
            fail("ERR_REQUISITE_CYCLE", "the edge would close a prerequisite cycle")

    for existing in db.requisites.values():
        if (
            existing["status"] == "ACTIVE"
            and existing["course_id"] == course["id"]
            and existing["requisite_course_id"] == requisite_course["id"]
            and existing["requisite_type"] == body["requisite_type"]
        ):
            fail("ERR_DUPLICATE_REQUISITE", "an identical ACTIVE edge already exists")

    row = base_row()
    row.update({
        "course_id": course["id"],
        "requisite_course_id": requisite_course["id"],
        "requisite_type": body["requisite_type"],
        "min_grade": body.get("min_grade", "C"),
        "enforcement": body.get("enforcement", "BLOCKING"),
        "status": "ACTIVE",
    })
    db.requisites[row["id"]] = row

    # PRD 3.1: a requirement added mid-term takes hold immediately.
    for reg in sort_rows(list(db.registrations.values())):
        if reg["state"] == "PENDING" and calc.section_course_id(reg["section_id"]) == course["id"]:
            calc.recompute_registration_prerequisite(reg)

    return created(serialize.requisite(row))


@bp.get("/course-requisites/<requisite_id>")
def get_requisite(requisite_id):
    authenticate(READERS)
    parse_query({}, paginated=False)
    row = find("requisites", requisite_id)
    return ok(serialize.requisite(row))


@bp.get("/course-requisites")
def list_requisites():
    authenticate(READERS)
    query = parse_query(LIST_SPEC)
    rows = filter_rows(list(db.requisites.values()), query, {
        "course_id": eq("course_id"),
        "requisite_course_id": eq("requisite_course_id"),
        "requisite_type": eq("requisite_type"),
        "enforcement": eq("enforcement"),
        "status": eq("status"),
    })
    return listing(rows, query, serialize.requisite)


@bp.post("/course-requisites/<requisite_id>/retire")
def retire_requisite(requisite_id):
    authenticate(("SystemAdmin",))
    parse_body({})
    row = find("requisites", requisite_id)
    if row["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "only an ACTIVE requisite edge may be retired")
    cascades.retire_requisite_edge(row)
    return ok(serialize.requisite(row))
