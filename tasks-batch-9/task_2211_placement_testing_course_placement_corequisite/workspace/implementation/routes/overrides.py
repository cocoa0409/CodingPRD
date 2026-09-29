"""Prerequisite overrides: issuance and revocation of BLOCKING waivers."""

from flask import Blueprint

from constants import OVERRIDE_STATES
from db import base_row, db, touch
from errors import fail
from middleware import authenticate
from response import created, ok
from routes.common import eq, filter_rows, find, listing
from services import calc, serialize
from validators import Field, parse_body, parse_query

bp = Blueprint("overrides", __name__)

READERS = ("Instructor", "Registrar", "SystemAdmin", "Student")

CREATE_SPEC = {
    "student_id": Field("id", required=True),
    "course_id": Field("id", required=True),
    "requisite_id": Field("id", required=True),
    "justification": Field("str", required=True, min_len=10, max_len=1000),
    "expires_at": Field("datetime", required=True),
}

LIST_SPEC = {
    "student_id": Field("id"),
    "course_id": Field("id"),
    "requisite_id": Field("id"),
    "consumed_by_registration_id": Field("id"),
    "state": Field("enum", values=OVERRIDE_STATES),
    "issued_by_user_id": Field("str"),
}


@bp.post("/prerequisite-overrides")
def create_override():
    user_id, _role = authenticate(("Instructor", "Registrar"))
    body = parse_body(CREATE_SPEC)

    student = find("students", body["student_id"])
    course = find("courses", body["course_id"])
    edge = find("requisites", body["requisite_id"])

    if (
        edge["course_id"] != course["id"]
        or edge["requisite_type"] != "PREREQUISITE"
        or edge["enforcement"] != "BLOCKING"
    ):
        fail("ERR_INVALID_REQUEST", "requisite_id is not a BLOCKING PREREQUISITE of the course")
    if course["status"] == "RETIRED":
        fail("ERR_COURSE_RETIRED", "the course is retired")

    row = base_row()
    row.update({
        "student_id": student["id"],
        "course_id": course["id"],
        "requisite_id": edge["id"],
        "justification": body["justification"],
        "expires_at": body["expires_at"],
        "issued_by_user_id": user_id,
        "consumed_by_registration_id": None,
        "state": "ISSUED",
    })
    db.overrides[row["id"]] = row
    return created(serialize.override(row))


@bp.get("/prerequisite-overrides/<override_id>")
def get_override(override_id):
    authenticate(READERS)
    parse_query({}, paginated=False)
    row = find("overrides", override_id)
    return ok(serialize.override(row))


@bp.get("/prerequisite-overrides")
def list_overrides():
    authenticate(READERS)
    query = parse_query(LIST_SPEC)
    rows = filter_rows(list(db.overrides.values()), query, {
        "student_id": eq("student_id"),
        "course_id": eq("course_id"),
        "requisite_id": eq("requisite_id"),
        "consumed_by_registration_id": eq("consumed_by_registration_id"),
        "state": eq("state"),
        "issued_by_user_id": eq("issued_by_user_id"),
    })
    return listing(rows, query, serialize.override)


@bp.post("/prerequisite-overrides/<override_id>/revoke")
def revoke(override_id):
    user_id, role = authenticate(("Instructor", "Registrar"))
    parse_body({})
    row = find("overrides", override_id)

    if row["state"] == "CONSUMED":
        fail("ERR_OVERRIDE_CONSUMED", "the consuming registration must be dropped first")
    if row["state"] != "ISSUED":
        fail("ERR_INVALID_STATE", "only an ISSUED override may be revoked")
    if role == "Instructor" and user_id != row["issued_by_user_id"]:
        fail("ERR_NOT_OVERRIDE_ISSUER", "an instructor may only revoke their own override")

    row["state"] = "REVOKED"
    touch(row)

    for reg in db.registrations.values():
        if reg["override_id"] == row["id"] and reg["state"] in ("PENDING", "WAITLISTED"):
            calc.recompute_registration_prerequisite(reg)
    return ok(serialize.override(row))
