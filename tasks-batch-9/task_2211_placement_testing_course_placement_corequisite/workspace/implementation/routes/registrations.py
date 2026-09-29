"""Registrations: holding, confirming, dropping and grading a seat."""

from flask import Blueprint

from constants import FINAL_GRADES, MAX_TERM_UNITS, REGISTRATION_STATES, WAITLIST_CAP
from db import base_row, db, touch
from errors import fail
from middleware import authenticate
from response import created, ok
from routes.common import eq, filter_rows, find, listing
from services import calc, cascades, serialize
from validators import Field, parse_body, parse_query

bp = Blueprint("registrations", __name__)

READERS = ("Registrar", "SystemAdmin", "Instructor", "AssessmentStaff", "Student")
LIVE_STATES = ("PENDING", "ENROLLED", "WAITLISTED", "COMPLETED")

CREATE_SPEC = {
    "student_id": Field("id", required=True),
    "section_id": Field("id", required=True),
    "override_id": Field("id", nullable=True),
    "expected_section_version": Field("int", required=True),
}

LIST_SPEC = {
    "student_id": Field("id"),
    "section_id": Field("id"),
    "coreq_registration_id": Field("id"),
    "override_id": Field("id"),
    "state": Field("enum", values=REGISTRATION_STATES),
    "term_code": Field("str"),
    "final_grade": Field("enum", values=FINAL_GRADES),
}

GRADE_SPEC = {"final_grade": Field("enum", required=True, values=FINAL_GRADES)}


def _term_code(reg):
    section = db.sections.get(reg["section_id"])
    return section["term_code"] if section else None


@bp.post("/registrations")
def create_registration():
    authenticate(("Registrar", "Student"))
    body = parse_body(CREATE_SPEC)

    student = find("students", body["student_id"])
    section = find("sections", body["section_id"])
    override = None
    if body.get("override_id") is not None:
        override = find("overrides", body["override_id"])

    if body["expected_section_version"] != section["version"]:
        fail("ERR_STALE_SECTION_VERSION", "expected_section_version does not match")

    if section["status"] != "OPEN":
        fail("ERR_SECTION_NOT_OPEN", "the section is not accepting holds")
    if override is not None:
        if override["state"] != "ISSUED":
            fail("ERR_OVERRIDE_CONSUMED", "the override is not available for redemption")
        if override["expires_at"] <= db.clock:
            fail("ERR_OVERRIDE_EXPIRED", "the override has expired")

    for existing in db.registrations.values():
        if (
            existing["student_id"] == student["id"]
            and existing["section_id"] == section["id"]
            and existing["state"] in LIVE_STATES
        ):
            fail("ERR_DUPLICATE_REGISTRATION", "the student already holds this section")

    row = base_row()
    row.update({
        "student_id": student["id"],
        "section_id": section["id"],
        "coreq_registration_id": None,
        "override_id": override["id"] if override else None,
        "prerequisite_status": "SATISFIED",
        "term_units_at_confirm": None,
        "final_grade": None,
        "graded_at": None,
        "denial_reason": None,
        "state": "PENDING",
    })
    row["prerequisite_status"] = calc.prerequisite_status(
        student["id"], section["course_id"], row["override_id"]
    )
    db.registrations[row["id"]] = row
    touch(section)
    return created(serialize.registration(row))


@bp.get("/registrations/<registration_id>")
def get_registration(registration_id):
    authenticate(READERS)
    parse_query({}, paginated=False)
    row = find("registrations", registration_id)
    return ok(serialize.registration(row))


@bp.get("/registrations")
def list_registrations():
    authenticate(READERS)
    query = parse_query(LIST_SPEC)
    rows = filter_rows(list(db.registrations.values()), query, {
        "student_id": eq("student_id"),
        "section_id": eq("section_id"),
        "coreq_registration_id": eq("coreq_registration_id"),
        "override_id": eq("override_id"),
        "state": eq("state"),
        "final_grade": eq("final_grade"),
        "term_code": lambda r, v: _term_code(r) == v,
    })
    return listing(rows, query, serialize.registration)


def _governing_determination(student_id, subject_area):
    candidates = [
        d for d in db.determinations.values()
        if d["student_id"] == student_id
        and d["subject_area"] == subject_area
        and d["placement_state"] in ("PROVISIONAL", "FINAL")
        and d["evidence_state"] != "DISPUTED"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda d: (d["determined_at"], d["created_at"], d["_seq"]))
    return candidates[-1]


@bp.post("/registrations/<registration_id>/confirm")
def confirm(registration_id):
    authenticate(("Registrar",))
    parse_body({})
    row = find("registrations", registration_id)

    if row["state"] != "PENDING":
        fail("ERR_INVALID_STATE", "only a PENDING hold may be confirmed")
    section = db.sections.get(row["section_id"])
    if section is None or section["status"] != "OPEN":
        fail("ERR_SECTION_NOT_OPEN", "the section is not OPEN")

    course = db.courses.get(section["course_id"])
    determination = _governing_determination(
        row["student_id"], course["subject_area"] if course else None
    )
    if determination is None:
        fail("ERR_PLACEMENT_NOT_ACTIONABLE", "no actionable determination governs this course")

    if calc.prerequisite_status(row["student_id"], section["course_id"], row["override_id"]) == "UNMET":
        fail("ERR_PREREQUISITE_NOT_MET", "the prerequisite closure is UNMET")

    if section["course_id"] not in (
        determination["placed_course_id"], determination["coreq_course_id"]
    ):
        fail("ERR_PLACEMENT_COURSE_MISMATCH", "the section's course is not the placed course")

    units = calc.term_unit_load(row, section)
    if units > MAX_TERM_UNITS:
        fail("ERR_TERM_UNIT_CAP_EXCEEDED", "the term unit cap of eighteen units is exceeded")

    ctx = cascades.new_ctx()
    if calc.available_seats(section, exclude_registration_id=row["id"]) >= 1:
        cascades.enroll_registration(row, section, ctx)
    else:
        _taken, _held, waitlisted = calc.section_counts(section)
        if waitlisted >= WAITLIST_CAP:
            fail("ERR_SECTION_FULL", "the section and its waitlist are both full")
        row["state"] = "WAITLISTED"
        row["term_units_at_confirm"] = units
        touch(row)
        cascades.mark_section(ctx, section["id"])
    cascades.settle(ctx, promote=False)
    return ok(serialize.registration(row))


@bp.post("/registrations/<registration_id>/drop")
def drop(registration_id):
    user_id, role = authenticate(("Registrar", "Student"))
    parse_body({})
    row = find("registrations", registration_id)

    if row["state"] not in ("PENDING", "ENROLLED", "WAITLISTED"):
        fail("ERR_INVALID_STATE", "the registration is already terminal")
    if row["state"] == "ENROLLED":
        section = db.sections.get(row["section_id"])
        if section is None or section["status"] not in ("OPEN", "CLOSED"):
            fail("ERR_SECTION_NOT_OPEN", "the section is not OPEN or CLOSED")
    if role == "Student" and user_id != row["student_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "a student may only drop their own registration")

    cascades.drop_registration(row)
    return ok(serialize.registration(row))


@bp.post("/registrations/<registration_id>/grade")
def grade(registration_id):
    authenticate(("Instructor",))
    body = parse_body(GRADE_SPEC)
    row = find("registrations", registration_id)

    if row["state"] != "ENROLLED":
        fail("ERR_INVALID_STATE", "only an ENROLLED registration may be graded")
    section = db.sections.get(row["section_id"])
    if section is None or section["status"] != "CLOSED":
        fail("ERR_SECTION_NOT_CLOSED", "the section must be CLOSED before grading")
    if db.clock < section["meets_end_at"]:
        fail("ERR_INVALID_STATE", "the section has not finished meeting")

    row["final_grade"] = body["final_grade"]
    row["graded_at"] = db.clock
    row["state"] = "COMPLETED"
    touch(row)

    course = db.courses.get(section["course_id"])
    if course is not None:
        touch(course)
    return ok(serialize.registration(row))
