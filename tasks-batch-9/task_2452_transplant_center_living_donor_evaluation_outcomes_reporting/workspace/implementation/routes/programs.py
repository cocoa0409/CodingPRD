"""Programs, staff members, operating rooms, the compliance sweep, and the clock."""

from decimal import Decimal

from flask import Blueprint, g

import calc
import domain
import serialize
from db import db, new_entity, now, touch
from errors import ApiError
from middleware import ALL_ROLES, authenticate
from response import list_response, object_response
from util import add_days, parse_dt
from validation import (
    get_body,
    opt_bool,
    opt_enum,
    opt_int,
    opt_num,
    pagination,
    q_bool,
    q_enum,
    req_dt,
    req_str,
)

bp = Blueprint("programs", __name__)


def find_program(program_id):
    program = db.programs.get(program_id)
    if program is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND", "no TransplantProgram with id %s" % program_id)
    return program


def find_staff(staff_id):
    staff = db.staff_members.get(staff_id)
    if staff is None:
        raise ApiError("ERR_STAFF_NOT_FOUND", "no StaffMember with id %s" % staff_id)
    return staff


def find_room(room_id):
    room = db.rooms.get(room_id)
    if room is None:
        raise ApiError("ERR_ROOM_NOT_FOUND", "no OperatingRoom with id %s" % room_id)
    return room


@bp.post("/programs")
def create_program():
    authenticate(["ProgramAdmin"])
    body = get_body()
    name = req_str(body, "name")
    center_code = req_str(body, "center_code")
    organ_type = opt_enum(body, "organ_type", calc.ORGAN_TYPES, "KIDNEY")
    cooling_off_days = opt_int(body, "cooling_off_days", 7, minimum=1)
    completeness_threshold = opt_num(
        body, "follow_up_completeness_threshold_pct", 80, minimum=0, maximum=100, exclusive_min=True
    )
    compliance_threshold = opt_num(
        body, "follow_up_compliance_threshold_pct", 75, minimum=0, maximum=100, exclusive_min=True
    )
    survival_rate = opt_num(
        body, "expected_one_year_survival_rate", 0.95, minimum=0, maximum=1, exclusive_min=True
    )
    pool_cents = opt_int(body, "donor_fund_pool_cents", 5000000, minimum=0)
    daily_cap = opt_int(body, "lost_wage_daily_cap_cents", 30000, minimum=0)
    weekly_cap = opt_int(body, "lost_wage_weekly_cap_cents", 150000, minimum=0)

    for existing in db.programs.values():
        if existing["center_code"] == center_code:
            raise ApiError("ERR_DUPLICATE_CENTER_CODE", "center_code %s is taken" % center_code)

    row = new_entity(
        "TransplantProgram",
        {
            "name": name,
            "center_code": center_code,
            "organ_type": organ_type,
            "cooling_off_days": cooling_off_days,
            "follow_up_completeness_threshold_pct": completeness_threshold,
            "follow_up_compliance_threshold_pct": compliance_threshold,
            "expected_one_year_survival_rate": survival_rate,
            "donor_fund_pool_cents": pool_cents,
            "lost_wage_daily_cap_cents": daily_cap,
            "lost_wage_weekly_cap_cents": weekly_cap,
            "compliance_posture": "OPEN",
            "last_sweep_at": None,
        },
    )
    db.programs[row["id"]] = row
    return object_response(serialize.program(row), 201)


@bp.get("/programs/<program_id>")
def get_program(program_id):
    authenticate(ALL_ROLES)
    program = find_program(program_id)
    return object_response(serialize.program(program))


@bp.post("/programs/<program_id>/compliance-sweep")
def compliance_sweep(program_id):
    authenticate(["QualityOfficer", "ProgramAdmin"])
    program = find_program(program_id)
    clock = now()

    for follow_up in domain.follow_ups_of_program(program):
        if follow_up["status"] in ("DUE", "INCOMPLETE"):
            if clock >= add_days(follow_up["due_on"], calc.DELINQUENCY_GRACE_DAYS):
                follow_up["status"] = "DELINQUENT"
                touch(follow_up)

    domain.refresh_posture(program)
    program["last_sweep_at"] = clock
    touch(program)
    return object_response(serialize.program(program))


# --------------------------------------------------------------------------- #
# staff members
# --------------------------------------------------------------------------- #


@bp.post("/staff-members")
def create_staff_member():
    authenticate(["ProgramAdmin"])
    body = get_body()
    program_id = req_str(body, "program_id")
    full_name = req_str(body, "full_name")
    staff_role = req_str(body, "staff_role")
    if staff_role not in calc.STAFF_ROLES:
        raise ApiError("ERR_VALIDATION", "staff_role must be one of %s" % ", ".join(calc.STAFF_ROLES))
    npi = req_str(body, "npi")
    is_active = opt_bool(body, "is_active", True)

    program = find_program(program_id)

    for existing in db.staff_members.values():
        if existing["program_id"] == program["id"] and existing["npi"] == npi:
            raise ApiError("ERR_DUPLICATE_NPI", "npi %s is taken in this program" % npi)

    row = new_entity(
        "StaffMember",
        {
            "program_id": program["id"],
            "full_name": full_name,
            "staff_role": staff_role,
            "npi": npi,
            "is_active": is_active,
        },
    )
    db.staff_members[row["id"]] = row
    return object_response(serialize.staff_member(row), 201)


@bp.get("/programs/<program_id>/staff-members")
def list_staff_members(program_id):
    authenticate(ALL_ROLES)
    program = find_program(program_id)
    staff_role = q_enum("staff_role", calc.STAFF_ROLES)
    is_active = q_bool("is_active")
    limit, offset = pagination()

    rows = [s for s in db.staff_members.values() if s["program_id"] == program["id"]]
    if staff_role is not None:
        rows = [s for s in rows if s["staff_role"] == staff_role]
    if is_active is not None:
        rows = [s for s in rows if s["is_active"] == is_active]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serialize.staff_member(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------- #
# operating rooms
# --------------------------------------------------------------------------- #


@bp.post("/operating-rooms")
def create_operating_room():
    authenticate(["ProgramAdmin"])
    body = get_body()
    program_id = req_str(body, "program_id")
    room_code = req_str(body, "room_code")
    buffer_minutes = opt_int(body, "turnover_buffer_minutes", 45, minimum=0)

    program = find_program(program_id)

    for existing in db.rooms.values():
        if existing["program_id"] == program["id"] and existing["room_code"] == room_code:
            raise ApiError("ERR_DUPLICATE_ROOM_CODE", "room_code %s is taken" % room_code)

    row = new_entity(
        "OperatingRoom",
        {
            "program_id": program["id"],
            "room_code": room_code,
            "turnover_buffer_minutes": buffer_minutes,
        },
    )
    db.rooms[row["id"]] = row
    return object_response(serialize.operating_room(row), 201)


@bp.get("/programs/<program_id>/operating-rooms")
def list_operating_rooms(program_id):
    authenticate(ALL_ROLES)
    program = find_program(program_id)
    limit, offset = pagination()
    rows = [r for r in db.rooms.values() if r["program_id"] == program["id"]]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serialize.operating_room(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------- #
# logical clock
# --------------------------------------------------------------------------- #


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(["ProgramAdmin"])
    body = get_body()
    target = req_dt(body, "current_utc")
    if target < db.clock:
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC", "the logical clock may not move backwards")
    db.clock = target
    return object_response({})
