"""Test attempts: booking, the retake budget, proctoring and voiding."""

from flask import Blueprint

from constants import ATTEMPT_STATES, MAX_ATTEMPTS_PER_SUBJECT, RULE_SUBJECTS, VOID_REASONS
from db import base_row, db, touch
from errors import fail
from middleware import authenticate
from response import created, ok
from routes.common import eq, filter_rows, find, listing
from services import calc, cascades, serialize
from validators import Field, parse_body, parse_query

bp = Blueprint("attempts", __name__)

READERS = ("AssessmentStaff", "Proctor", "AssessmentDirector", "Registrar", "Student")

CREATE_SPEC = {
    "student_id": Field("id", required=True),
    "administration_id": Field("id", required=True),
}

LIST_SPEC = {
    "student_id": Field("id"),
    "administration_id": Field("id"),
    "state": Field("enum", values=ATTEMPT_STATES),
    "subject_area": Field("enum", values=RULE_SUBJECTS),
    "irregularity_flag": Field("bool"),
}

SCORE_SPEC = {
    "raw_score": Field("int", required=True, minimum=0, maximum=160),
    "irregularity_flag": Field("bool"),
}

VOID_SPEC = {"void_reason": Field("enum", required=True, values=VOID_REASONS)}


@bp.post("/test-attempts")
def create_attempt():
    authenticate(("AssessmentStaff", "Student"))
    body = parse_body(CREATE_SPEC)

    student = find("students", body["student_id"])
    admin = find("administrations", body["administration_id"])

    if admin["status"] in ("CLOSED", "CANCELLED"):
        fail("ERR_ADMINISTRATION_NOT_BOOKABLE", "the session is no longer bookable")

    subject = admin["subject_area"]

    gate = calc.booking_gate(student["id"], subject)
    if gate is not None and gate > admin["starts_at"]:
        fail("ERR_RETAKE_WAITING_PERIOD", "the retake waiting period has not elapsed")

    scored = calc.scored_attempt_counts(student["id"]).get(subject, 0)
    if MAX_ATTEMPTS_PER_SUBJECT - scored <= 0:
        fail("ERR_ATTEMPT_LIMIT_REACHED", "no remaining attempts in this subject")
    for attempt in db.attempts.values():
        if (
            attempt["student_id"] == student["id"]
            and attempt["subject_area"] == subject
            and attempt["state"] in ("BOOKED", "CHECKED_IN")
        ):
            fail("ERR_ATTEMPT_ALREADY_OPEN", "an attempt in this subject is already open")
    if calc.admin_computed(admin)["seats_booked"] >= admin["seat_capacity"]:
        fail("ERR_ADMINISTRATION_FULL", "the session has no seat left")

    row = base_row()
    row.update({
        "student_id": student["id"],
        "administration_id": admin["id"],
        "subject_area": subject,
        "attempt_ordinal": 0,
        "raw_score": None,
        "scaled_score": None,
        "irregularity_flag": False,
        "scored_at": None,
        "next_eligible_at": None,
        "void_reason": None,
        "state": "BOOKED",
    })
    db.attempts[row["id"]] = row

    pool = calc.attempt_pool(student["id"], subject)
    for index, attempt in enumerate(pool, start=1):
        if attempt["id"] == row["id"]:
            row["attempt_ordinal"] = index
    calc.renumber_attempts(student["id"], subject)

    return created(serialize.attempt(row))


@bp.get("/test-attempts/<attempt_id>")
def get_attempt(attempt_id):
    authenticate(READERS)
    parse_query({}, paginated=False)
    row = find("attempts", attempt_id)
    return ok(serialize.attempt(row))


@bp.get("/test-attempts")
def list_attempts():
    authenticate(READERS)
    query = parse_query(LIST_SPEC)
    rows = filter_rows(list(db.attempts.values()), query, {
        "student_id": eq("student_id"),
        "administration_id": eq("administration_id"),
        "state": eq("state"),
        "subject_area": eq("subject_area"),
        "irregularity_flag": eq("irregularity_flag"),
    })
    return listing(rows, query, serialize.attempt)


@bp.post("/test-attempts/<attempt_id>/check-in")
def check_in(attempt_id):
    user_id, _role = authenticate(("Proctor",))
    parse_body({})
    row = find("attempts", attempt_id)

    if row["state"] != "BOOKED":
        fail("ERR_INVALID_STATE", "only a BOOKED attempt may be checked in")
    admin = db.administrations.get(row["administration_id"])
    if admin is None or admin["status"] != "OPEN":
        fail("ERR_ADMINISTRATION_NOT_OPEN", "the session is not OPEN")
    if user_id != admin["proctor_user_id"]:
        fail("ERR_NOT_ASSIGNED_PROCTOR", "X-User-ID is not the session's assigned proctor")
    if not (admin["starts_at"] <= db.clock < admin["ends_at"]):
        fail("ERR_INVALID_STATE", "the logical clock is outside the sitting window")

    row["state"] = "CHECKED_IN"
    touch(row)
    return ok(serialize.attempt(row))


@bp.post("/test-attempts/<attempt_id>/score")
def score(attempt_id):
    user_id, _role = authenticate(("Proctor",))
    body = parse_body(SCORE_SPEC)
    row = find("attempts", attempt_id)

    if row["state"] != "CHECKED_IN":
        fail("ERR_INVALID_STATE", "only a CHECKED_IN attempt may be scored")
    admin = db.administrations.get(row["administration_id"])
    if admin is None or admin["status"] != "OPEN":
        fail("ERR_ADMINISTRATION_NOT_OPEN", "the session is not OPEN")
    if user_id != admin["proctor_user_id"]:
        fail("ERR_NOT_ASSIGNED_PROCTOR", "X-User-ID is not the session's assigned proctor")

    flag = body.get("irregularity_flag", False)
    row["raw_score"] = body["raw_score"]
    row["irregularity_flag"] = flag
    row["scored_at"] = db.clock
    row["scaled_score"] = calc.scaled_score(body["raw_score"], flag)
    row["state"] = "SCORED"
    touch(row)

    calc.renumber_attempts(row["student_id"], row["subject_area"])

    student = db.students.get(row["student_id"])
    if student is not None:
        touch(student)
    return ok(serialize.attempt(row))


@bp.post("/test-attempts/<attempt_id>/void")
def void(attempt_id):
    authenticate(("Proctor", "AssessmentStaff"))
    body = parse_body(VOID_SPEC)
    row = find("attempts", attempt_id)

    if row["state"] != "SCORED":
        fail("ERR_INVALID_STATE", "only a SCORED attempt may be voided")

    cascades.void_attempt(row, body["void_reason"])
    return ok(serialize.attempt(row))


@bp.post("/test-attempts/<attempt_id>/no-show")
def no_show(attempt_id):
    authenticate(("Proctor",))
    parse_body({})
    row = find("attempts", attempt_id)

    if row["state"] != "BOOKED":
        fail("ERR_INVALID_STATE", "only a BOOKED attempt may be marked as a no-show")

    row["state"] = "NO_SHOW"
    row["next_eligible_at"] = None
    touch(row)
    return ok(serialize.attempt(row))
