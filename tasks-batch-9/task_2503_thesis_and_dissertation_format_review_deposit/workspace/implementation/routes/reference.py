"""Registrar groundwork: terms, rosters, rooms, the term runs and the clock."""

import re

import lookup
import serializers
import validate
from db import db, new_row, write
from errors import fail
from flask import Blueprint
from logical_clock import clock
from middleware import endpoint
from response import object_response
from routes.common import ALL_ROLES, PREFIX
from services import calc
from services.clearance import recompute
from timeutil import iso

bp = Blueprint("reference", __name__, url_prefix=PREFIX)

TERM_CODE_RE = re.compile(r"^[0-9]{4}(SP|SU|FA)$")

DEGREE_LEVELS = ("MASTERS", "DOCTORAL")
APPOINTMENT_TYPES = ("TENURED", "TENURE_TRACK", "ADJUNCT", "EXTERNAL")
ROOM_STATUSES = ("AVAILABLE", "MAINTENANCE")


# --------------------------------------------------------------------- reads


@bp.get("/terms/<term_id>")
@endpoint(ALL_ROLES)
def read_term(user_id, role, term_id):
    return object_response(serializers.term(lookup.get_term(term_id)))


@bp.get("/students/<student_id>")
@endpoint(ALL_ROLES)
def read_student(user_id, role, student_id):
    return object_response(serializers.student(lookup.get_student(student_id)))


@bp.get("/students/<student_id>/graduation-clearances")
@endpoint(ALL_ROLES)
def read_student_clearances(user_id, role, student_id):
    limit, offset = validate.pagination()
    student = lookup.get_student(student_id)
    clearance = lookup.clearance_of_student(student["id"])
    rows = [clearance] if clearance is not None else []
    page, total = validate.paginate(rows, limit, offset)
    from response import array_response

    return array_response(
        [serializers.graduation_clearance(row) for row in page], limit, offset, total
    )


@bp.get("/faculty-members/<faculty_id>")
@endpoint(ALL_ROLES)
def read_faculty(user_id, role, faculty_id):
    return object_response(serializers.faculty_member(lookup.get_faculty(faculty_id)))


@bp.get("/defense-rooms/<room_id>")
@endpoint(ALL_ROLES)
def read_room(user_id, role, room_id):
    return object_response(serializers.defense_room(lookup.get_room(room_id)))


# -------------------------------------------------------------------- writes


@bp.post("/terms")
@endpoint(["Registrar"])
def create_term(user_id, role):
    body = validate.get_body()
    code = validate.req_str(body, "code")
    defense_deadline = validate.req_datetime(body, "defense_deadline")
    deposit_deadline = validate.req_datetime(body, "format_review_deposit_deadline")
    conferral_date = validate.req_datetime(body, "degree_conferral_date")
    lead = validate.opt_int(
        body, "announcement_lead_business_days", default=10, minimum=1
    )
    if not TERM_CODE_RE.match(code):
        fail(
            "ERR_INVALID_REQUEST",
            "Field 'code' must be a four-digit year followed by SP, SU or FA",
        )
    for existing in db.terms.values():
        if existing["code"] == code:
            fail("ERR_INVALID_REQUEST", "Term code '%s' already exists" % code)

    row = new_row(
        code=code,
        announcement_lead_business_days=lead,
        defense_deadline=defense_deadline,
        format_review_deposit_deadline=deposit_deadline,
        degree_conferral_date=conferral_date,
        status="OPEN",
        conferred_count=0,
    )
    db.terms[row["id"]] = row
    return object_response(serializers.term(row), 201)


@bp.post("/students")
@endpoint(["Registrar"])
def create_student(user_id, role):
    body = validate.get_body()
    full_name = validate.req_str(body, "full_name")
    email = validate.req_str(body, "email")
    degree_level = validate.req_enum(body, "degree_level", DEGREE_LEVELS)
    program_code = validate.req_str(body, "program_code")
    for existing in db.students.values():
        if existing["email"] == email:
            fail("ERR_INVALID_REQUEST", "Student email '%s' already exists" % email)

    row = new_row(
        full_name=full_name,
        email=email,
        degree_level=degree_level,
        program_code=program_code,
        graduation_clearance_state="BLOCKED",
        degree_conferred=False,
        transcript_notation=None,
    )
    db.students[row["id"]] = row
    return object_response(serializers.student(row), 201)


@bp.post("/faculty-members")
@endpoint(["Registrar"])
def create_faculty(user_id, role):
    body = validate.get_body()
    full_name = validate.req_str(body, "full_name")
    email = validate.req_str(body, "email")
    appointment_type = validate.req_enum(body, "appointment_type", APPOINTMENT_TYPES)
    certified = validate.opt_bool(body, "graduate_faculty_certified", default=False)
    for existing in db.faculty_members.values():
        if existing["email"] == email:
            fail("ERR_INVALID_REQUEST", "Faculty email '%s' already exists" % email)

    row = new_row(
        full_name=full_name,
        email=email,
        appointment_type=appointment_type,
        graduate_faculty_certified=certified,
        active_chair_load=0,
    )
    db.faculty_members[row["id"]] = row
    return object_response(serializers.faculty_member(row), 201)


@bp.post("/defense-rooms")
@endpoint(["Registrar"])
def create_room(user_id, role):
    body = validate.get_body()
    code = validate.req_str(body, "code")
    building = validate.req_str(body, "building")
    seat_capacity = validate.req_int(body, "seat_capacity", minimum=1)
    buffer_minutes = validate.opt_int(
        body, "turnover_buffer_minutes", default=30, minimum=0
    )
    status = validate.opt_enum(body, "status", ROOM_STATUSES, default="AVAILABLE")
    for existing in db.defense_rooms.values():
        if existing["code"] == code:
            fail("ERR_INVALID_REQUEST", "Room code '%s' already exists" % code)

    row = new_row(
        code=code,
        building=building,
        seat_capacity=seat_capacity,
        turnover_buffer_minutes=buffer_minutes,
        status=status,
        booked_minutes_total=0,
    )
    db.defense_rooms[row["id"]] = row
    return object_response(serializers.defense_room(row), 201)


# ----------------------------------------------------------------- term runs


@bp.post("/terms/<term_id>/close-deposit")
@endpoint(["Registrar"])
def close_deposit(user_id, role, term_id):
    term = lookup.get_term(term_id)
    if term["status"] != "OPEN":
        fail("ERR_TERM_STATE_INVALID", "Only an OPEN term can close its deposit window")

    write(term, status="DEPOSIT_CLOSED")

    seen = []
    for thesis in sorted(
        lookup.theses_of_term(term["id"]), key=lambda r: (r["created_at"], r["_seq"])
    ):
        if thesis["student_id"] not in seen:
            seen.append(thesis["student_id"])
    for student_id in seen:
        recompute(student_id, variant="FINAL")

    return object_response(serializers.term(term))


@bp.post("/terms/<term_id>/confer-degrees")
@endpoint(["Registrar"])
def confer_degrees(user_id, role, term_id):
    term = lookup.get_term(term_id)
    if term["status"] != "DEPOSIT_CLOSED":
        fail(
            "ERR_TERM_STATE_INVALID",
            "Conferral may only be posted for a DEPOSIT_CLOSED term",
        )

    conferred_count = 0
    withheld_count = 0
    pending_count = 0

    for thesis in sorted(
        lookup.theses_of_term(term["id"]),
        key=lambda r: (r["created_at"], r["version"], r["_seq"]),
    ):
        clearance = recompute(thesis["student_id"], variant="FINAL")
        if clearance is None:
            pending_count += 1
            continue
        student = db.students.get(thesis["student_id"])

        if (
            thesis["workflow_state"] == "TERMINATED"
            or thesis["integrity_state"] == "INTEGRITY_UPHELD"
        ):
            write(
                clearance,
                status="WITHHELD",
                withheld_reason=calc.WITHHOLD_REASON,
                transcript_notation=calc.WITHHOLD_NOTATION,
                cleared_at=None,
            )
            if student is not None:
                write(
                    student,
                    graduation_clearance_state="WITHHELD",
                    transcript_notation=calc.WITHHOLD_NOTATION,
                    degree_conferred=False,
                )
            withheld_count += 1
            continue

        if clearance["status"] == "CLEARED":
            deposit = None
            for row in lookup.deposits_of_thesis(thesis["id"]):
                if row["status"] == "DEPOSITED":
                    deposit = row
                    break
            notation = None
            if deposit is not None:
                notation = calc.conferral_notation(
                    thesis["document_type"],
                    deposit["deposited_at"],
                    deposit["embargo_release_date"],
                )
            if thesis["workflow_state"] == "DEPOSITED":
                write(thesis, workflow_state="CONFERRED")
            write(
                clearance,
                status="CONFERRED",
                conferral_posted_at=clock.now(),
                transcript_notation=notation,
            )
            if student is not None:
                write(
                    student,
                    graduation_clearance_state="CONFERRED",
                    degree_conferred=True,
                    transcript_notation=notation,
                )
            conferred_count += 1
            continue

        pending_count += 1

    write(term, status="CONFERRED", conferred_count=conferred_count)

    return object_response(
        {
            "term_id": term["id"],
            "conferred_count": conferred_count,
            "withheld_count": withheld_count,
            "pending_count": pending_count,
        }
    )


# --------------------------------------------------------------- clock driver


@bp.post("/_clock/set_current_utc")
@endpoint(["Registrar"])
def set_clock(user_id, role):
    body = validate.get_body()
    instant = validate.req_datetime(body, "to_iso8601")
    clock.set(instant)
    return object_response({"current_utc": iso(clock.now())})
