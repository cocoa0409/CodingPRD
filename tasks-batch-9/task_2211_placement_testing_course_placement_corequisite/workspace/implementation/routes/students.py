"""Students, their multiple measures and their determination sub-listing."""

from decimal import Decimal

from flask import Blueprint

from constants import EL_STATUSES, PATHWAYS, PLACEMENT_STATES, RACE_ETHNICITY_CODES, RULE_SUBJECTS, TRANSCRIPT_STATUSES
from db import base_row, db, touch
from errors import fail
from middleware import authenticate
from response import created, ok
from routes.common import eq, filter_rows, find, listing
from services import calc, serialize
from validators import Field, parse_body, parse_query

bp = Blueprint("students", __name__)

ALL_READERS = (
    "SystemAdmin",
    "AssessmentStaff",
    "AssessmentDirector",
    "Registrar",
    "Instructor",
    "Student",
)

GPA = Field("dec", places=2, minimum=Decimal("0.00"), maximum=Decimal("4.50"), nullable=True)

CREATE_SPEC = {
    "student_number": Field("str", required=True, min_len=1, max_len=20),
    "full_name": Field("str", required=True),
    "race_ethnicity_code": Field("enum", required=True, values=RACE_ETHNICITY_CODES),
    "first_generation": Field("bool"),
    "pell_eligible": Field("bool"),
    "el_status": Field("enum", values=EL_STATUSES),
    "hs_gpa": GPA,
    "hs_transcript_status": Field("enum", values=TRANSCRIPT_STATUSES),
    "transcript_recorded_at": Field("datetime", nullable=True),
    "self_guided_pathway": Field("enum", values=PATHWAYS, nullable=True),
}

MEASURES_SPEC = {
    "hs_gpa": GPA,
    "hs_transcript_status": Field("enum", values=TRANSCRIPT_STATUSES),
    "transcript_recorded_at": Field("datetime", nullable=True),
    "self_guided_pathway": Field("enum", values=PATHWAYS, nullable=True),
    "el_status": Field("enum", values=EL_STATUSES),
}

LIST_SPEC = {
    "student_number": Field("str"),
    "el_status": Field("enum", values=EL_STATUSES),
    "placement_status": Field("enum", values=("UNPLACED", "PROVISIONAL", "FINAL")),
    "hs_transcript_status": Field("enum", values=TRANSCRIPT_STATUSES),
}

DETERMINATION_LIST_SPEC = {
    "subject_area": Field("enum", values=RULE_SUBJECTS),
    "placement_state": Field("enum", values=PLACEMENT_STATES),
}


@bp.post("/students")
def create_student():
    authenticate(("SystemAdmin", "AssessmentStaff"))
    body = parse_body(CREATE_SPEC)

    for existing in db.students.values():
        if existing["student_number"] == body["student_number"]:
            fail("ERR_DUPLICATE_STUDENT_NUMBER", "student_number is already on the roster")

    row = base_row()
    row.update({
        "student_number": body["student_number"],
        "full_name": body["full_name"],
        "race_ethnicity_code": body["race_ethnicity_code"],
        "first_generation": body.get("first_generation", False),
        "pell_eligible": body.get("pell_eligible", False),
        "el_status": body.get("el_status", "NOT_EL"),
        "hs_gpa": body.get("hs_gpa"),
        "transcript_recorded_at": body.get("transcript_recorded_at"),
        "hs_transcript_status": body.get("hs_transcript_status", "NONE"),
        "self_guided_pathway": body.get("self_guided_pathway"),
    })
    db.students[row["id"]] = row
    return created(serialize.student(row))


@bp.get("/students/<student_id>")
def get_student(student_id):
    authenticate(ALL_READERS)
    parse_query({}, paginated=False)
    row = find("students", student_id)
    return ok(serialize.student(row))


@bp.get("/students")
def list_students():
    authenticate(("SystemAdmin", "AssessmentStaff", "AssessmentDirector", "Registrar"))
    query = parse_query(LIST_SPEC)
    rows = filter_rows(list(db.students.values()), query, {
        "student_number": eq("student_number"),
        "el_status": eq("el_status"),
        "hs_transcript_status": eq("hs_transcript_status"),
        "placement_status": lambda r, v: calc.student_computed(r)["placement_status"] == v,
    })
    return listing(rows, query, serialize.student)


@bp.post("/students/<student_id>/measures")
def update_measures(student_id):
    user_id, role = authenticate(("AssessmentStaff", "Student"))
    body = parse_body(MEASURES_SPEC)
    row = find("students", student_id)
    if role == "Student" and user_id != row["id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "a student may only revise their own measures")

    for name in ("hs_gpa", "hs_transcript_status", "transcript_recorded_at",
                 "self_guided_pathway", "el_status"):
        if name in body:
            row[name] = body[name]
    touch(row)
    return ok(serialize.student(row))


@bp.get("/students/<student_id>/determinations")
def list_student_determinations(student_id):
    authenticate(ALL_READERS)
    query = parse_query(DETERMINATION_LIST_SPEC)
    row = find("students", student_id)
    rows = [d for d in db.determinations.values() if d["student_id"] == row["id"]]
    rows = filter_rows(rows, query, {
        "subject_area": eq("subject_area"),
        "placement_state": eq("placement_state"),
    })
    rows.sort(key=lambda d: (d["determined_at"], d["created_at"], d["_seq"]))
    return listing(rows, query, serialize.determination, presorted=True)
