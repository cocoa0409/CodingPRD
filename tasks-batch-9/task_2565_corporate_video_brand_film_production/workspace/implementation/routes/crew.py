"""Crew roster, bookings, the scheduling guards and the clock (PRD 2.5, 3.6)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import derive
import workflow
from auth import authenticate
from envelope import respond_created, respond_list, respond_object
from errors import ApiError
from lookups import find_crew_booking, find_crew_member, find_shoot_day
from store import db, iso, new_row, parse_instant, touch
from validation import (field_enum, field_identifier, field_instant, field_integer,
                        field_string, json_body, paginate, pagination, require_interval)

bp = Blueprint("crew", __name__)

DEPARTMENTS = ("CAMERA", "GRIP_ELECTRIC", "SOUND", "ART", "PRODUCTION", "POST")
ACTIVE_BOOKING_STATES = ("HELD", "CONFIRMED")


# --------------------------------------------------------------------------
# Roster
# --------------------------------------------------------------------------
@bp.get("/crew-members/<crew_member_id>")
def read_crew_member(crew_member_id):
    authenticate(("ProductionCoordinator", "LineProducer", "CrewMember"))
    crew_member = find_crew_member(crew_member_id)
    return respond_object(derive.crew_member_out(crew_member))


@bp.post("/crew-members")
def create_crew_member():
    authenticate(("ProductionCoordinator", "LineProducer"))
    body = json_body()
    full_name = field_string(body, "full_name", 1, 120)
    department = field_enum(body, "department", DEPARTMENTS)
    hourly_rate_cents = field_integer(body, "hourly_rate_cents", minimum=1)
    union_local = field_string(body, "union_local", 1, 120, required=False, default=None)
    min_turnaround_hours = field_integer(body, "min_turnaround_hours", 0, 24,
                                         required=False, default=10)
    row = new_row(
        full_name=full_name,
        department=department,
        hourly_rate_cents=hourly_rate_cents,
        min_turnaround_hours=min_turnaround_hours,
        union_local=union_local,
    )
    db["crew_members"][row["id"]] = row
    return respond_created(derive.crew_member_out(row))


# --------------------------------------------------------------------------
# Bookings
# --------------------------------------------------------------------------
@bp.get("/crew-bookings/<booking_id>")
def read_crew_booking(booking_id):
    caller = authenticate(("ProductionCoordinator", "LineProducer", "CrewMember"))
    booking = find_crew_booking(booking_id)
    if caller.role == "CrewMember" and booking["crew_member_id"] != caller.user_id:
        raise ApiError("ERR_CREW_SCOPE_FORBIDDEN",
                       "A CrewMember may only read its own bookings.")
    return respond_object(derive.crew_booking_out(booking))


@bp.get("/crew-bookings")
def list_crew_bookings():
    caller = authenticate(("ProductionCoordinator", "LineProducer", "CrewMember"))
    crew_member_id = request.args.get("crew_member_id")
    if caller.role == "CrewMember" and crew_member_id != caller.user_id:
        raise ApiError("ERR_CREW_SCOPE_FORBIDDEN",
                       "A CrewMember must scope the booking list to its own crew_member_id.")
    limit, offset = pagination()
    rows = list(db["crew_bookings"].values())
    shoot_day_id = request.args.get("shoot_day_id")
    if shoot_day_id is not None:
        rows = [r for r in rows if r["shoot_day_id"] == shoot_day_id]
    if crew_member_id is not None:
        rows = [r for r in rows if r["crew_member_id"] == crew_member_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=lambda r: (r["call_time"], r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return respond_list([derive.crew_booking_out(r) for r in page], limit, offset, total)


def _person_bookings(crew_member_id):
    return [r for r in db["crew_bookings"].values()
            if r["crew_member_id"] == crew_member_id and r["status"] in ACTIVE_BOOKING_STATES]


@bp.post("/crew-bookings")
def create_crew_booking():
    authenticate(("ProductionCoordinator",))
    body = json_body()
    shoot_day_id = field_identifier(body, "shoot_day_id")
    crew_member_id = field_identifier(body, "crew_member_id")
    department_role = field_string(body, "department_role", 1, 80)
    call_time = field_instant(body, "call_time")
    wrap_time = field_instant(body, "wrap_time")
    require_interval(call_time, wrap_time, "call_time", "wrap_time")

    shoot_day = find_shoot_day(shoot_day_id)
    crew_member = find_crew_member(crew_member_id)
    if shoot_day["status"] not in ("PLANNED", "CONFIRMED"):
        raise ApiError("ERR_SHOOT_DAY_STATE_INVALID",
                       "A %s day accepts no new bookings." % shoot_day["status"])

    others = _person_bookings(crew_member["id"])
    # Closed interval: touching endpoints DO intersect -- deliberately stricter
    # than the half-open stage-capacity rule of PRD 3.4.
    disjoint = []
    for other in others:
        other_call = parse_instant(other["call_time"])
        other_wrap = parse_instant(other["wrap_time"])
        if call_time <= other_wrap and other_call <= wrap_time:
            raise ApiError("ERR_CREW_DOUBLE_BOOKED",
                           "This crew member already holds an overlapping booking.")
        disjoint.append((other_call, other_wrap))

    minimum = Decimal(int(crew_member["min_turnaround_hours"])) * Decimal(3600)
    for other_call, other_wrap in disjoint:
        if call_time > other_wrap:
            gap = Decimal(int((call_time - other_wrap).total_seconds()))
        else:
            gap = Decimal(int((other_call - wrap_time).total_seconds()))
        if gap < minimum:
            raise ApiError("ERR_CREW_TURNAROUND_VIOLATION",
                           "The rest gap is below this crew member's %d-hour turnaround."
                           % crew_member["min_turnaround_hours"])

    money = calc.crew_booking_cost(call_time, wrap_time, crew_member["hourly_rate_cents"])
    project = derive.project_of_shoot_day(shoot_day)
    workflow.enforce_allowance(project, money["cost_cents"])

    watch = workflow.LedgerWatch(project)
    row = new_row(
        shoot_day_id=shoot_day["id"],
        crew_member_id=crew_member["id"],
        department_role=department_role,
        call_time=iso(call_time),
        wrap_time=iso(wrap_time),
        scheduled_hours=money["scheduled_hours"],
        straight_time_cents=money["straight_time_cents"],
        overtime_tier1_cents=money["overtime_tier1_cents"],
        overtime_tier2_cents=money["overtime_tier2_cents"],
        cost_cents=money["cost_cents"],
        status="HELD",
    )
    db["crew_bookings"][row["id"]] = row
    watch.finish()
    return respond_created(derive.crew_booking_out(row))


@bp.post("/crew-bookings/<booking_id>/confirm")
def confirm_crew_booking(booking_id):
    authenticate(("ProductionCoordinator",))
    json_body(required=False)
    booking = find_crew_booking(booking_id)
    if booking["status"] != "HELD":
        raise ApiError("ERR_CREW_BOOKING_STATE_INVALID",
                       "Confirmation requires the booking to be HELD.")
    shoot_day = db["shoot_days"].get(booking["shoot_day_id"])
    if shoot_day["status"] not in ("PLANNED", "CONFIRMED"):
        raise ApiError("ERR_SHOOT_DAY_STATE_INVALID",
                       "A %s day accepts no booking confirmation." % shoot_day["status"])
    project = derive.project_of_shoot_day(shoot_day)
    watch = workflow.LedgerWatch(project)
    booking["status"] = "CONFIRMED"
    touch(booking)
    watch.finish()
    return respond_object(derive.crew_booking_out(booking))


@bp.post("/crew-bookings/<booking_id>/release")
def release_crew_booking(booking_id):
    authenticate(("ProductionCoordinator",))
    body = json_body(required=False)
    release_reason = field_string(body, "release_reason", 1, 2000, required=False, default=None)
    booking = find_crew_booking(booking_id)
    if booking["status"] not in ACTIVE_BOOKING_STATES:
        raise ApiError("ERR_CREW_BOOKING_STATE_INVALID",
                       "A %s booking may not be released." % booking["status"])
    shoot_day = db["shoot_days"].get(booking["shoot_day_id"])
    project = derive.project_of_shoot_day(shoot_day) if shoot_day else None
    watch = workflow.LedgerWatch(project)
    booking["status"] = "RELEASED"
    booking["_release_reason"] = release_reason
    touch(booking)
    watch.finish()
    return respond_object(derive.crew_booking_out(booking))
