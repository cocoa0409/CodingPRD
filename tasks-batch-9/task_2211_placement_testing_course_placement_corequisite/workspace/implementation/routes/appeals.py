"""Placement appeals: review cycle, endorsement, decision and withdrawal."""

from datetime import timedelta

from flask import Blueprint

from constants import (
    APPEAL_FILING_WINDOW_DAYS,
    APPEAL_GROUNDS,
    APPEAL_MAX_REVISION_ROUNDS,
    APPEAL_RESUBMIT_DAYS,
    APPEAL_STATES,
)
from db import base_row, db, sort_rows, touch
from errors import fail
from middleware import authenticate
from response import created, ok
from routes.common import eq, filter_rows, find, listing
from services import cascades, serialize
from validators import Field, parse_body, parse_query

bp = Blueprint("appeals", __name__)

READERS = ("Registrar", "Instructor", "AssessmentStaff", "AssessmentDirector", "Student")
LIVE_APPEAL_STATES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "INSTRUCTOR_ENDORSED")

CREATE_SPEC = {
    "determination_id": Field("id", required=True),
    "requested_course_id": Field("id", required=True),
    "grounds": Field("enum", required=True, values=APPEAL_GROUNDS),
    "statement": Field("str", required=True, min_len=1, max_len=2000),
    "expected_determination_version": Field("int", required=True),
}

LIST_SPEC = {
    "determination_id": Field("id"),
    "student_id": Field("id"),
    "requested_course_id": Field("id"),
    "minted_determination_id": Field("id"),
    "state": Field("enum", values=APPEAL_STATES),
    "grounds": Field("enum", values=APPEAL_GROUNDS),
}

INFO_SPEC = {"info_request_note": Field("str", required=True)}
RESUBMIT_SPEC = {"statement": Field("str", required=True, min_len=1, max_len=2000)}
ENDORSE_SPEC = {"decision_note": Field("str", nullable=True)}
DECIDE_SPEC = {
    "decision": Field("enum", required=True, values=("GRANT", "DENY")),
    "decision_note": Field("str", required=True),
}


@bp.post("/placement-appeals")
def file_appeal():
    authenticate(("Student", "Registrar"))
    body = parse_body(CREATE_SPEC)

    det = find("determinations", body["determination_id"])
    course = find("courses", body["requested_course_id"])

    if body["expected_determination_version"] != det["version"]:
        fail("ERR_STALE_DETERMINATION_VERSION", "expected_determination_version does not match")

    if det["placement_state"] in ("APPEALED", "SUPERSEDED"):
        fail("ERR_PLACEMENT_NOT_ACTIONABLE", "the determination is not appealable")

    student = db.students.get(det["student_id"])
    if body["grounds"] == "EL_PATHWAY":
        if student is None or student["el_status"] not in ("EL_ACTIVE", "EL_EXITED"):
            fail("ERR_EL_PATHWAY_VIOLATION", "EL_PATHWAY grounds require an EL student")

    if db.clock >= det["determined_at"] + timedelta(days=APPEAL_FILING_WINDOW_DAYS):
        fail("ERR_APPEAL_WINDOW_CLOSED", "the thirty-day filing window has closed")

    for other in sort_rows(list(db.appeals.values())):
        if other["determination_id"] == det["id"] and other["state"] in LIVE_APPEAL_STATES:
            other["state"] = "WITHDRAWN"
            other["decided_at"] = db.clock
            other["decision_note"] = "superseded by a newer appeal"
            touch(other)

    row = base_row()
    row.update({
        "determination_id": det["id"],
        "student_id": det["student_id"],
        "requested_course_id": course["id"],
        "grounds": body["grounds"],
        "statement": body["statement"],
        "revision_round": 0,
        "info_request_note": None,
        "reviewed_by_user_id": None,
        "endorsed_by_user_id": None,
        "decision_note": None,
        "filed_at": db.clock,
        "decided_at": None,
        "minted_determination_id": None,
        "state": "SUBMITTED",
    })
    db.appeals[row["id"]] = row

    det["placement_state"] = "APPEALED"
    touch(det)
    if student is not None:
        touch(student)

    return created(serialize.appeal(row))


@bp.get("/placement-appeals/<appeal_id>")
def get_appeal(appeal_id):
    authenticate(READERS)
    parse_query({}, paginated=False)
    row = find("appeals", appeal_id)
    return ok(serialize.appeal(row))


@bp.get("/placement-appeals")
def list_appeals():
    authenticate(READERS)
    query = parse_query(LIST_SPEC)
    rows = filter_rows(list(db.appeals.values()), query, {
        "determination_id": eq("determination_id"),
        "student_id": eq("student_id"),
        "requested_course_id": eq("requested_course_id"),
        "minted_determination_id": eq("minted_determination_id"),
        "state": eq("state"),
        "grounds": eq("grounds"),
    })
    return listing(rows, query, serialize.appeal)


@bp.post("/placement-appeals/<appeal_id>/start-review")
def start_review(appeal_id):
    user_id, _role = authenticate(("Registrar",))
    parse_body({})
    row = find("appeals", appeal_id)

    if row["state"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "only a SUBMITTED appeal may be taken under review")
    det = db.determinations.get(row["determination_id"])
    if det is None or det["placement_state"] != "APPEALED":
        fail("ERR_INVALID_STATE", "the appealed determination is not in APPEALED")
    if user_id == det["determined_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the author of the placement may not review its appeal")

    row["state"] = "UNDER_REVIEW"
    if row["reviewed_by_user_id"] is None:
        row["reviewed_by_user_id"] = user_id
    touch(row)
    return ok(serialize.appeal(row))


@bp.post("/placement-appeals/<appeal_id>/request-info")
def request_info(appeal_id):
    user_id, _role = authenticate(("Registrar",))
    body = parse_body(INFO_SPEC)
    row = find("appeals", appeal_id)

    if row["state"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "only an UNDER_REVIEW appeal may be sent back")
    if user_id != row["reviewed_by_user_id"]:
        fail("ERR_NOT_APPEAL_REVIEWER", "only the owning reviewer may request information")
    if row["revision_round"] >= APPEAL_MAX_REVISION_ROUNDS:
        fail("ERR_APPEAL_ROUND_LIMIT", "the appeal has exhausted its revision rounds")

    row["state"] = "INFO_REQUESTED"
    row["info_request_note"] = body["info_request_note"]
    touch(row)
    return ok(serialize.appeal(row))


@bp.post("/placement-appeals/<appeal_id>/resubmit")
def resubmit(appeal_id):
    user_id, role = authenticate(("Student", "Registrar"))
    body = parse_body(RESUBMIT_SPEC)
    row = find("appeals", appeal_id)

    if row["state"] != "INFO_REQUESTED":
        fail("ERR_INVALID_STATE", "only an INFO_REQUESTED appeal may be resubmitted")
    if role == "Student" and user_id != row["student_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "a student may only resubmit their own appeal")
    if db.clock >= row["filed_at"] + timedelta(days=APPEAL_RESUBMIT_DAYS):
        fail("ERR_APPEAL_WINDOW_CLOSED", "the fourteen-day resubmission window has closed")

    row["statement"] = body["statement"]
    row["state"] = "UNDER_REVIEW"
    row["revision_round"] = row["revision_round"] + 1
    row["info_request_note"] = None
    touch(row)
    return ok(serialize.appeal(row))


@bp.post("/placement-appeals/<appeal_id>/endorse")
def endorse(appeal_id):
    user_id, _role = authenticate(("Instructor",))
    body = parse_body(ENDORSE_SPEC)
    row = find("appeals", appeal_id)

    if row["state"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "only an UNDER_REVIEW appeal may be endorsed")
    course = db.courses.get(row["requested_course_id"])
    if course is None or course["status"] != "ACTIVE":
        fail("ERR_COURSE_RETIRED", "the requested course is retired")
    if user_id == row["reviewed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the reviewer may not endorse their own case")

    row["state"] = "INSTRUCTOR_ENDORSED"
    row["endorsed_by_user_id"] = user_id
    if body.get("decision_note") is not None:
        row["decision_note"] = body["decision_note"]
    touch(row)
    return ok(serialize.appeal(row))


@bp.post("/placement-appeals/<appeal_id>/decide")
def decide(appeal_id):
    user_id, _role = authenticate(("Registrar",))
    body = parse_body(DECIDE_SPEC)
    row = find("appeals", appeal_id)

    decision = body["decision"]
    if decision == "GRANT":
        if row["state"] != "INSTRUCTOR_ENDORSED":
            fail("ERR_APPEAL_NOT_ENDORSED", "a grant requires an instructor endorsement")
    else:
        if row["state"] not in ("UNDER_REVIEW", "INSTRUCTOR_ENDORSED"):
            fail("ERR_INVALID_STATE", "the appeal is not in a decidable state")

    det = db.determinations.get(row["determination_id"])
    if det is not None and user_id == det["determined_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the author of the placement may not decide its appeal")
    if user_id != row["reviewed_by_user_id"]:
        fail("ERR_NOT_APPEAL_REVIEWER", "only the owning reviewer may decide the appeal")

    row["decided_at"] = db.clock
    row["decision_note"] = body["decision_note"]

    if decision == "GRANT":
        row["state"] = "GRANTED"
        touch(row)
        cascades.grant_appeal(row, det, user_id)
    else:
        row["state"] = "DENIED"
        touch(row)
        cascades.release_determination_from_appealed(det)
        if det is not None:
            student = db.students.get(det["student_id"])
            if student is not None:
                touch(student)
    return ok(serialize.appeal(row))


@bp.post("/placement-appeals/<appeal_id>/withdraw")
def withdraw(appeal_id):
    user_id, role = authenticate(("Student", "Registrar"))
    parse_body({})
    row = find("appeals", appeal_id)

    if row["state"] not in LIVE_APPEAL_STATES:
        fail("ERR_INVALID_STATE", "the appeal is already terminal")
    if role == "Student" and user_id != row["student_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "a student may only withdraw their own appeal")

    row["state"] = "WITHDRAWN"
    row["decided_at"] = db.clock
    row["decision_note"] = "appeal withdrawn"
    touch(row)

    det = db.determinations.get(row["determination_id"])
    cascades.release_determination_from_appealed(det)
    if det is not None:
        student = db.students.get(det["student_id"])
        if student is not None:
            touch(student)
    return ok(serialize.appeal(row))
