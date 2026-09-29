"""Shift assignments: reservation, confirmation, check-in, release."""
from decimal import Decimal

from flask import Blueprint

import calc
import cascade
import derive
from common import (
    API, created, get_assignment, get_member, get_shift, get_volunteer, listing, match, okay,
)
from errors import fail
from payload import body, qenum, qid, venum, vint, vstring
from rbac import auth
from store import bump, db, stamp
from util import date_start, dec, minutes, r2

bp = Blueprint("assignments", __name__)

ROLES = ("GENERAL_VOLUNTEER", "SKILLED_TRADE", "HOMEOWNER_PARTNER")
SEAT_STATES = ("RESERVED", "CONFIRMED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW")
SEAT_TERMINALS = ("COMPLETED", "CANCELLED", "NO_SHOW")
CHECK_IN_LEAD = minutes(30)


def _site_clear(site):
    if site is not None and (site.get("safety_posture") == "HOLD"
                             or site.get("readiness_status") == "SAFETY_HOLD"):
        fail("ERR_SITE_UNDER_SAFETY_HOLD")


def _guard_profile(volunteer, shift, role):
    if volunteer.get("status") == "SUSPENDED":
        fail("ERR_VOLUNTEER_SUSPENDED")
    waiver = date_start(volunteer.get("waiver_expires_on"))
    if waiver is None or waiver <= shift["start_at"]:
        fail("ERR_WAIVER_EXPIRED")
    if role == "SKILLED_TRADE":
        wanted = shift.get("required_trade")
        for certification in (volunteer.get("trade_certifications") or []):
            if certification.get("trade") != wanted:
                continue
            expires = date_start(certification.get("expires_on"))
            if expires is not None and expires > shift["end_at"]:
                return
        fail("ERR_TRADE_CERTIFICATION_INVALID")


@bp.post(API + "/shift-assignments")
def create_assignment():
    actor = auth("ConstructionManager", "Volunteer", "Applicant")
    data = body()

    raw_shift = data.get("shift_id")
    shift = get_shift(raw_shift) if isinstance(raw_shift, str) and raw_shift else None
    raw_volunteer = data.get("volunteer_id")
    volunteer = get_volunteer(raw_volunteer) if isinstance(raw_volunteer, str) and raw_volunteer else None
    raw_member = data.get("household_member_id")
    member = get_member(raw_member) if isinstance(raw_member, str) and raw_member else None

    shift_id = vstring(data, "shift_id", 1, None, required=True)
    expected = vint(data, "expected_shift_version", minimum=1, required=True)
    role = venum(data, "role", ROLES, required=True)
    if shift is None:
        shift = get_shift(shift_id)

    if role == "HOMEOWNER_PARTNER":
        if member is None:
            fail("ERR_VALIDATION", "household_member_id is required for a partner seat.")
        if volunteer is not None:
            fail("ERR_VALIDATION", "A partner seat may not name a volunteer_id.")
    else:
        if volunteer is None:
            fail("ERR_VALIDATION", "volunteer_id is required for a community seat.")
        if member is not None:
            fail("ERR_VALIDATION", "A community seat may not name a household_member_id.")

    if actor.role == "Volunteer":
        if volunteer is None or volunteer["id"] != actor.entity_id:
            fail("ERR_NOT_RESOURCE_OWNER")
    if actor.role == "Applicant":
        if member is None or member.get("household_id") != actor.entity_id:
            fail("ERR_NOT_RESOURCE_OWNER")

    site = derive.site_of_shift(shift)
    cascade.guard_not_frozen(derive.program_of_site(site) if site else None)

    if int(shift.get("version") or 0) != int(expected):
        fail("ERR_STALE_SHIFT_VERSION")

    cascade.state_gate(shift, "status", ("SCHEDULED", "OPEN"),
                       ("COMPLETED", "CANCELLED"))
    _site_clear(site)

    # 28 volunteer eligibility, 29 interval overlap
    if role != "HOMEOWNER_PARTNER":
        _guard_profile(volunteer, shift, role)
        if calc.volunteer_overlap(volunteer["id"], shift) is not None:
            fail("ERR_VOLUNTEER_DOUBLE_BOOKED")

    # 30 seat inventory
    if role == "GENERAL_VOLUNTEER":
        if calc.seat_count(shift, role) + 1 > (shift.get("volunteer_slots") or 0):
            fail("ERR_SHIFT_ROLE_FULL")
    elif role == "SKILLED_TRADE":
        allowance = (shift.get("required_trade_slots") or 0) + 2
        if calc.seat_count(shift, role) + 1 > allowance:
            fail("ERR_SHIFT_ROLE_FULL")
    else:
        if site is None or member.get("household_id") != site.get("assigned_household_id"):
            fail("ERR_PARTNER_MEMBER_NOT_ON_SITE")
        if member.get("status") != "ACTIVE":
            fail("ERR_MEMBER_NOT_ACTIVE")

    # 31 weekly capacity
    if role != "HOMEOWNER_PARTNER":
        total = r2(calc.weekly_hours(volunteer["id"], shift)
                   + dec(shift.get("duration_hours") or 0))
        if total > calc.weekly_cap(volunteer):
            fail("ERR_VOLUNTEER_WEEKLY_CAP_EXCEEDED")

    row = {
        "shift_id": shift["id"],
        "volunteer_id": volunteer["id"] if volunteer is not None else None,
        "household_member_id": member["id"] if member is not None else None,
        "role": role,
        "checked_in_at": None,
        "status": "RESERVED",
    }
    stamp(row)
    db.assignments[row["id"]] = row

    derive.refresh_shift(shift)
    bump(shift)
    if volunteer is not None:
        derive.refresh_volunteer(volunteer)
        bump(volunteer)
    return created(derive.public_assignment(row))


@bp.get(API + "/shift-assignments")
def list_assignments():
    actor = auth("ProgramAdmin", "ConstructionManager", "FamilyServicesCoordinator",
                 "Volunteer", "Applicant")
    shift_id = qid("shift_id")
    volunteer_id = qid("volunteer_id")
    member_id = qid("household_member_id")
    role = qenum("role", ROLES)
    status = qenum("status", SEAT_STATES)
    rows = [r for r in db.assignments.values()
            if match(r, "shift_id", shift_id)
            and match(r, "volunteer_id", volunteer_id)
            and match(r, "household_member_id", member_id)
            and match(r, "role", role)
            and match(r, "status", status)]
    rows = _scope(actor, rows)
    return listing(rows, derive.public_assignment)


def _scope(actor, rows):
    if actor.role == "Volunteer":
        return [r for r in rows if r.get("volunteer_id") == actor.entity_id]
    if actor.role == "Applicant":
        kept = []
        for row in rows:
            member = db.members.get(row.get("household_member_id"))
            if member is not None and member.get("household_id") == actor.entity_id:
                kept.append(row)
        return kept
    return rows


def _own(actor, seat):
    if actor.role == "Volunteer":
        if seat.get("volunteer_id") != actor.entity_id:
            fail("ERR_NOT_RESOURCE_OWNER")
    if actor.role == "Applicant":
        member = db.members.get(seat.get("household_member_id"))
        if member is None or member.get("household_id") != actor.entity_id:
            fail("ERR_NOT_RESOURCE_OWNER")


@bp.get(API + "/shift-assignments/<aid>")
def read_assignment(aid):
    actor = auth("ProgramAdmin", "ConstructionManager", "FamilyServicesCoordinator",
                 "Volunteer", "Applicant")
    seat = get_assignment(aid)
    _own(actor, seat)
    return okay(derive.public_assignment(seat))


@bp.post(API + "/shift-assignments/<aid>/confirm")
def confirm_assignment(aid):
    actor = auth("ConstructionManager", "Volunteer", "Applicant")
    seat = get_assignment(aid)
    _own(actor, seat)
    body()

    shift = derive.shift_of_assignment(seat)
    site = derive.site_of_shift(shift) if shift else None
    cascade.guard_not_frozen(derive.program_of_site(site) if site else None)
    cascade.state_gate(seat, "status", ("RESERVED",), SEAT_TERMINALS)

    if shift is None or shift.get("status") not in ("SCHEDULED", "OPEN"):
        fail("ERR_TRANSITION_NOT_ALLOWED", "The shift is not accepting confirmations.")
    _site_clear(site)

    volunteer_id = seat.get("volunteer_id")
    if volunteer_id:
        volunteer = db.volunteers.get(volunteer_id)
        if volunteer is None or volunteer.get("status") != "ACTIVE":
            fail("ERR_VOLUNTEER_SUSPENDED")
        _guard_profile(volunteer, shift, seat.get("role"))

    seat["status"] = "CONFIRMED"
    bump(seat)
    derive.refresh_shift(shift)
    bump(shift)
    return okay(derive.public_assignment(seat))


@bp.post(API + "/shift-assignments/<aid>/check-in")
def check_in_assignment(aid):
    auth("ConstructionManager")
    seat = get_assignment(aid)
    body()

    shift = derive.shift_of_assignment(seat)
    site = derive.site_of_shift(shift) if shift else None
    cascade.guard_not_frozen(derive.program_of_site(site) if site else None)
    cascade.state_gate(seat, "status", ("CONFIRMED",), SEAT_TERMINALS)

    if shift is None or shift.get("status") != "LOCKED" or \
            not shift.get("safety_briefing_completed"):
        fail("ERR_TRANSITION_NOT_ALLOWED", "The shift roster is not locked.")
    _site_clear(site)

    now = db.now()
    if now < shift["start_at"] - CHECK_IN_LEAD or now >= shift["end_at"]:
        fail("ERR_CHECK_IN_WINDOW_CLOSED")

    seat["status"] = "CHECKED_IN"
    seat["checked_in_at"] = now
    bump(seat)
    derive.refresh_shift(shift)
    bump(shift)
    return okay(derive.public_assignment(seat))


@bp.post(API + "/shift-assignments/<aid>/cancel")
def cancel_assignment(aid):
    actor = auth("ConstructionManager", "Volunteer", "Applicant")
    seat = get_assignment(aid)
    _own(actor, seat)
    data = body()
    vstring(data, "cancellation_reason", 1, None, default=None, nullable=True)

    shift = derive.shift_of_assignment(seat)
    site = derive.site_of_shift(shift) if shift else None
    cascade.guard_not_frozen(derive.program_of_site(site) if site else None)
    cascade.state_gate(seat, "status", ("RESERVED", "CONFIRMED"), SEAT_TERMINALS)

    cascade.release_seat(seat, "CANCELLED")
    if shift is not None:
        derive.refresh_shift(shift)
        bump(shift)
    return okay(derive.public_assignment(seat))
