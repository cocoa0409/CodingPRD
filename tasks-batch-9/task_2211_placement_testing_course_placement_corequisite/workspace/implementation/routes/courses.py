"""Catalogue courses, retirement, the equity report and carried requisites."""

from decimal import Decimal

from flask import Blueprint

from constants import (
    COURSE_STATUSES,
    COURSE_SUBJECTS,
    DISAGGREGATION_KEYS,
    REQUISITE_TYPES,
)
from db import base_row, db
from errors import fail
from middleware import authenticate
from response import created, ok
from routes.common import eq, filter_rows, find, listing
from services import calc, cascades, serialize
from validators import Field, parse_body, parse_query

bp = Blueprint("courses", __name__)

READERS = (
    "SystemAdmin",
    "AssessmentStaff",
    "AssessmentDirector",
    "Registrar",
    "Instructor",
    "Student",
)

CREATE_SPEC = {
    "course_code": Field("str", required=True, min_len=2, max_len=16),
    "title": Field("str", required=True),
    "subject_area": Field("enum", required=True, values=COURSE_SUBJECTS),
    "level_rank": Field("int", required=True, minimum=1, maximum=100),
    "units": Field("dec", required=True, places=1, minimum=Decimal("0.5"), maximum=Decimal("6.0")),
    "is_support_course": Field("bool"),
    "transfer_level": Field("bool"),
}

LIST_SPEC = {
    "subject_area": Field("enum", values=COURSE_SUBJECTS),
    "is_support_course": Field("bool"),
    "transfer_level": Field("bool"),
    "status": Field("enum", values=COURSE_STATUSES),
}

EQUITY_SPEC = {
    "disaggregation_key": Field("enum", required=True, values=DISAGGREGATION_KEYS),
    "window_start_at": Field("datetime", required=True),
    "window_end_at": Field("datetime", required=True),
}

REQUISITE_LIST_SPEC = {
    "requisite_type": Field("enum", values=REQUISITE_TYPES),
    "status": Field("enum", values=COURSE_STATUSES),
}


@bp.post("/courses")
def create_course():
    authenticate(("SystemAdmin",))
    body = parse_body(CREATE_SPEC)

    for existing in db.courses.values():
        if existing["course_code"] == body["course_code"]:
            fail("ERR_DUPLICATE_COURSE_CODE", "course_code is already in the catalogue")

    row = base_row()
    row.update({
        "course_code": body["course_code"],
        "title": body["title"],
        "subject_area": body["subject_area"],
        "level_rank": body["level_rank"],
        "units": body["units"],
        "is_support_course": body.get("is_support_course", False),
        "transfer_level": body.get("transfer_level", False),
        "status": "ACTIVE",
    })
    db.courses[row["id"]] = row
    return created(serialize.course(row))


@bp.get("/courses/<course_id>")
def get_course(course_id):
    authenticate(READERS)
    parse_query({}, paginated=False)
    row = find("courses", course_id)
    return ok(serialize.course(row))


@bp.get("/courses")
def list_courses():
    authenticate(READERS)
    query = parse_query(LIST_SPEC)
    rows = filter_rows(list(db.courses.values()), query, {
        "subject_area": eq("subject_area"),
        "is_support_course": eq("is_support_course"),
        "transfer_level": eq("transfer_level"),
        "status": eq("status"),
    })
    return listing(rows, query, serialize.course)


@bp.post("/courses/<course_id>/retire")
def retire_course(course_id):
    authenticate(("SystemAdmin",))
    parse_body({})
    row = find("courses", course_id)

    if row["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "only an ACTIVE course may be retired")
    for section in db.sections.values():
        if section["course_id"] == row["id"] and section["status"] in ("PLANNED", "OPEN"):
            fail("ERR_COURSE_HAS_LIVE_SECTIONS", "a PLANNED or OPEN section still exists")

    cascades.retire_course(row)
    return ok(serialize.course(row))


@bp.get("/courses/<course_id>/equity-summary")
def equity_summary(course_id):
    authenticate(("AssessmentDirector", "AssessmentStaff"))
    query = parse_query(EQUITY_SPEC, paginated=False)
    row = find("courses", course_id)

    if query["window_end_at"] <= query["window_start_at"]:
        fail("ERR_INVALID_REQUEST", "window_end_at must be strictly after window_start_at")

    return ok(calc.equity_summary(
        row["id"],
        query["disaggregation_key"],
        query["window_start_at"],
        query["window_end_at"],
    ))


@bp.get("/courses/<course_id>/requisites")
def list_course_requisites(course_id):
    authenticate(("SystemAdmin", "AssessmentStaff", "Registrar", "Instructor", "Student"))
    query = parse_query(REQUISITE_LIST_SPEC)
    row = find("courses", course_id)
    rows = [q for q in db.requisites.values() if q["course_id"] == row["id"]]
    rows = filter_rows(rows, query, {
        "requisite_type": eq("requisite_type"),
        "status": eq("status"),
    })
    return listing(rows, query, serialize.requisite)
