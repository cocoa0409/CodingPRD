"""Construction shifts and volunteer profiles."""
from decimal import Decimal

from flask import Blueprint

import calc
import cascade
import derive
from common import API, created, get_program, get_shift, get_site, get_volunteer, listing, match, okay
from errors import fail
from payload import (
    body, qdatetime, qenum, qid, qstring, vdatetime, venum, vint, vlist, vstring,
)
from rbac import auth, own_volunteer, scope_volunteers
from store import bump, db, fresh, stamp
from util import dec, minutes, parse_dt, whole_years_between

bp = Blueprint("shifts", __name__)

SHIFT_STATES = ("SCHEDULED", "OPEN", "LOCKED", "COMPLETED", "CANCELLED")
SHIFT_TERMINALS = ("COMPLETED", "CANCELLED")
TRADES = ("ELECTRICAL", "PLUMBING", "HVAC", "ROOFING")
SHIFT_READ_ROLES = ("ProgramAdmin", "ConstructionManager", "FamilyServicesCoordinator",
                    "Volunteer")


def _guard_slots(shift_like):
    slots = shift_like.get("volunteer_slots") or 0
    trade_slots = shift_like.get("required_trade_slots") or 0
    if slots + trade_slots < 1:
        fail("ERR_SHIFT_HAS_NO_SLOTS")
    if trade_slots > slots:
        fail("ERR_SHIFT_HAS_NO_SLOTS")
    trade = shift_like.get("required_trade")
    if trade_slots > 0 and not trade:
        fail("ERR_REQUIRED_TRADE_MISSING")
    if trade and trade_slots == 0:
        fail("ERR_REQUIRED_TRADE_MISSING")


def _guard_safety(site):
    if site is not None and site.get("readiness_status") == "SAFETY_HOLD":
        fail("ERR_SITE_UNDER_SAFETY_HOLD")


# --------------------------------------------------------------------------- #
# construction shifts
# --------------------------------------------------------------------------- #
@bp.post(API + "/construction-shifts")
def create_shift():
    auth("ConstructionManager")
    data = body()
    raw = data.get("build_site_id")
    site = get_site(raw) if isinstance(raw, str) and raw else None

    site_id = vstring(data, "build_site_id", 1, None, required=True)
    crew_lead = vstring(data, "crew_lead_user_id", 1, None, required=True)
    start_at = vdatetime(data, "start_at", required=True)
    end_at = vdatetime(data, "end_at", required=True)
    slots = vint(data, "volunteer_slots", minimum=0, maximum=40, required=True)
    trade_slots = vint(data, "required_trade_slots", minimum=0, maximum=10, default=0)
    trade = venum(data, "required_trade", TRADES, default=None, nullable=True)
    if site is None:
        site = get_site(site_id)

    if end_at <= start_at:
        fail("ERR_VALIDATION", "end_at must be strictly after start_at.")
    if (end_at - start_at) > minutes(600):
        fail("ERR_VALIDATION", "A shift may span at most 10 hours.")

    cascade.guard_not_frozen(derive.program_of_site(site))
    _guard_safety(site)
    _guard_slots({"volunteer_slots": slots, "required_trade_slots": trade_slots,
                  "required_trade": trade})

    if calc.site_window_conflict(site, start_at, end_at) is not None:
        fail("ERR_SITE_SHIFT_BUFFER_CONFLICT")

    row = {
        "build_site_id": site["id"],
        "crew_lead_user_id": crew_lead,
        "start_at": start_at,
        "end_at": end_at,
        "duration_hours": calc.duration_hours(start_at, end_at),
        "volunteer_slots": slots,
        "required_trade_slots": trade_slots,
        "required_trade": trade,
        "confirmed_general_count": 0,
        "confirmed_trade_count": 0,
        "fill_ratio": Decimal(0),
        "safety_briefing_completed": False,
        "status": "SCHEDULED",
    }
    stamp(row)
    db.shifts[row["id"]] = row
    return created(derive.public_shift(row))


@bp.get(API + "/construction-shifts")
def list_shifts():
    auth(*SHIFT_READ_ROLES)
    site_id = qid("build_site_id")
    status = qenum("status", SHIFT_STATES)
    trade = qenum("required_trade", TRADES)
    starts_after = qdatetime("starts_after")
    starts_before = qdatetime("starts_before")
    rows = []
    for shift in db.shifts.values():
        if not match(shift, "build_site_id", site_id):
            continue
        if not match(shift, "status", status):
            continue
        if not match(shift, "required_trade", trade):
            continue
        if starts_after is not None and shift["start_at"] < starts_after:
            continue
        if starts_before is not None and shift["start_at"] > starts_before:
            continue
        rows.append(shift)
    return listing(rows, derive.public_shift)


@bp.get(API + "/construction-shifts/<sid>")
def read_shift(sid):
    auth(*SHIFT_READ_ROLES)
    shift = get_shift(sid)
    return okay(derive.public_shift(shift))


@bp.post(API + "/construction-shifts/<sid>/open")
def open_shift(sid):
    auth("ConstructionManager")
    shift = get_shift(sid)
    body()

    cascade.state_gate(shift, "status", ("SCHEDULED", "LOCKED"), SHIFT_TERMINALS)
    site = derive.site_of_shift(shift)
    cascade.guard_not_frozen(derive.program_of_site(site) if site else None)
    _guard_safety(site)

    if site is None or site.get("readiness_status") not in ("READY_TO_BUILD",
                                                            "UNDER_CONSTRUCTION"):
        fail("ERR_SITE_NOT_READY_TO_BUILD")
    _guard_slots(shift)

    if shift["start_at"] <= db.now():
        fail("ERR_TRANSITION_NOT_ALLOWED", "The shift has already started.")

    if shift["status"] == "LOCKED":
        for seat in derive.assignments_of_shift(shift):
            if seat["status"] in ("CHECKED_IN", "COMPLETED"):
                fail("ERR_TRANSITION_NOT_ALLOWED",
                     "A seat has already been checked in.")
        shift["safety_briefing_completed"] = False

    shift["status"] = "OPEN"
    derive.refresh_shift(shift)
    bump(shift)
    return okay(derive.public_shift(shift))


@bp.post(API + "/construction-shifts/<sid>/lock")
def lock_shift(sid):
    auth("ConstructionManager")
    shift = get_shift(sid)
    data = body()
    reference = vstring(data, "safety_briefing_reference", 1, None,
                        default=None, nullable=True)

    cascade.state_gate(shift, "status", ("OPEN",), SHIFT_TERMINALS)
    site = derive.site_of_shift(shift)
    cascade.guard_not_frozen(derive.program_of_site(site) if site else None)
    _guard_safety(site)

    if not reference:
        fail("ERR_DOCUMENTATION_INCOMPLETE")

    derive.refresh_shift(shift)
    if (shift.get("confirmed_trade_count") or 0) < (shift.get("required_trade_slots") or 0):
        fail("ERR_TRADE_COVERAGE_INSUFFICIENT")
    if (shift.get("confirmed_general_count") or 0) < calc.min_general_confirmations(shift):
        fail("ERR_SHIFT_FILL_INSUFFICIENT")
    if shift["start_at"] <= db.now():
        fail("ERR_TRANSITION_NOT_ALLOWED", "The shift has already started.")

    shift["status"] = "LOCKED"
    shift["safety_briefing_completed"] = True
    derive.refresh_shift(shift)
    bump(shift)

    for seat in derive.assignments_of_shift(shift):
        if seat["status"] == "RESERVED":
            cascade.release_seat(seat, "CANCELLED")

    if site is not None and site.get("readiness_status") == "READY_TO_BUILD":
        site["readiness_status"] = "UNDER_CONSTRUCTION"
        derive.refresh_site(site)
        bump(site)

    derive.refresh_shift(shift)
    return okay(derive.public_shift(shift))


@bp.post(API + "/construction-shifts/<sid>/complete")
def complete_shift(sid):
    auth("ConstructionManager")
    shift = get_shift(sid)
    data = body()
    vstring(data, "completion_note", 1, None, default=None, nullable=True)

    cascade.state_gate(shift, "status", ("LOCKED",), SHIFT_TERMINALS)
    site = derive.site_of_shift(shift)
    cascade.guard_not_frozen(derive.program_of_site(site) if site else None)

    if db.now() < shift["end_at"]:
        fail("ERR_SHIFT_NOT_ENDED")

    shift["status"] = "COMPLETED"
    bump(shift)

    suspended = []
    for seat in derive.assignments_of_shift(shift):
        if seat["status"] == "CHECKED_IN":
            seat["status"] = "COMPLETED"
            bump(seat)
            if seat.get("role") == "HOMEOWNER_PARTNER":
                _mint_partner_entry(shift, seat)
            volunteer_id = seat.get("volunteer_id")
            if volunteer_id:
                volunteer = db.volunteers.get(volunteer_id)
                if volunteer is not None:
                    derive.refresh_volunteer(volunteer)
                    bump(volunteer)
        elif seat["status"] == "CONFIRMED":
            seat["status"] = "NO_SHOW"
            bump(seat)
            volunteer_id = seat.get("volunteer_id")
            if volunteer_id:
                volunteer = db.volunteers.get(volunteer_id)
                if volunteer is not None:
                    derive.refresh_volunteer(volunteer)
                    bump(volunteer)
                    suspended.append(volunteer)

    for volunteer in suspended:
        cascade.suspend_volunteer_cascade(volunteer)

    derive.refresh_shift(shift)
    return okay(derive.public_shift(shift))


def _mint_partner_entry(shift, seat):
    member = db.members.get(seat.get("household_member_id"))
    if member is None:
        return None
    household = db.households.get(member.get("household_id"))
    if household is None:
        return None
    row = {
        "household_id": household["id"],
        "member_id": member["id"],
        "shift_assignment_id": seat["id"],
        "reversal_of_entry_id": None,
        "category": "CONSTRUCTION",
        "work_date": shift["start_at"],
        "hours_claimed": shift["duration_hours"],
        "credit_weight": None,
        "hours_credited": None,
        "capped_hours": Decimal("0.00"),
        "claimed_by_user_id": shift.get("crew_lead_user_id"),
        "verified_by_user_id": shift.get("crew_lead_user_id"),
        "status": "VERIFIED",
    }
    stamp(row)
    fresh(row)
    db.entries[row["id"]] = row
    return row


@bp.post(API + "/construction-shifts/<sid>/cancel")
def cancel_shift(sid):
    auth("ConstructionManager")
    shift = get_shift(sid)
    data = body()
    vstring(data, "cancellation_reason", 1, None, default=None, nullable=True)

    cascade.state_gate(shift, "status", ("SCHEDULED", "OPEN", "LOCKED"), SHIFT_TERMINALS)
    site = derive.site_of_shift(shift)
    cascade.guard_not_frozen(derive.program_of_site(site) if site else None)

    shift["status"] = "CANCELLED"
    bump(shift)
    cascade.cancel_shift_seats(shift)
    derive.refresh_shift(shift)
    return okay(derive.public_shift(shift))


# --------------------------------------------------------------------------- #
# volunteer profiles
# --------------------------------------------------------------------------- #
@bp.post(API + "/volunteers")
def create_volunteer():
    auth("ConstructionManager", "ProgramAdmin")
    data = body()
    raw = data.get("program_id")
    program = get_program(raw) if isinstance(raw, str) and raw else None

    program_id = vstring(data, "program_id", 1, None, required=True)
    full_name = vstring(data, "full_name", 1, 120, required=True)
    birth_date = vdatetime(data, "birth_date", required=True)
    waiver = vdatetime(data, "waiver_expires_on", required=True)
    certifications = vlist(data, "trade_certifications", default=None, nullable=True)
    if program is None:
        program = get_program(program_id)

    parsed_certifications = []
    for item in (certifications or []):
        if not isinstance(item, dict):
            fail("ERR_VALIDATION", "trade_certifications entries must be objects.")
        trade = item.get("trade")
        if trade not in TRADES:
            fail("ERR_VALIDATION", "trade_certifications[].trade is invalid.")
        expires = parse_dt(item.get("expires_on")) if isinstance(item.get("expires_on"), str) else None
        if expires is None:
            fail("ERR_VALIDATION", "trade_certifications[].expires_on is invalid.")
        parsed_certifications.append({"trade": trade, "expires_on": expires})

    age = whole_years_between(birth_date, db.now())
    row = {
        "program_id": program["id"],
        "full_name": full_name,
        "birth_date": birth_date,
        "is_minor": age is not None and age < 18,
        "waiver_expires_on": waiver,
        "trade_certifications": parsed_certifications,
        "assigned_hours_committed": Decimal("0.00"),
        "no_show_strikes": 0,
        "status": "ACTIVE",
    }
    stamp(row)
    db.volunteers[row["id"]] = row
    return created(derive.public_volunteer(row))


@bp.get(API + "/volunteers")
def list_volunteers():
    actor = auth("ProgramAdmin", "ConstructionManager", "Volunteer")
    program_id = qid("program_id")
    status = qenum("status", ("ACTIVE", "SUSPENDED"))
    certification = qenum("trade_certification", TRADES)
    rows = []
    for volunteer in db.volunteers.values():
        if not match(volunteer, "program_id", program_id):
            continue
        if not match(volunteer, "status", status):
            continue
        if certification is not None:
            trades = [c.get("trade") for c in (volunteer.get("trade_certifications") or [])]
            if certification not in trades:
                continue
        rows.append(volunteer)
    return listing(scope_volunteers(actor, rows), derive.public_volunteer)


@bp.get(API + "/volunteers/<vid>")
def read_volunteer(vid):
    actor = auth("ProgramAdmin", "ConstructionManager", "Volunteer")
    volunteer = get_volunteer(vid)
    own_volunteer(actor, volunteer)
    return okay(derive.public_volunteer(volunteer))
