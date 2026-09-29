"""Synchronous cascades. Every hop lands before the response is written."""
from decimal import Decimal

import calc
import derive
from errors import fail
from store import bump, db
from util import date_start, dec


# --------------------------------------------------------------------------- #
# guards
# --------------------------------------------------------------------------- #
def guard_not_frozen(program):
    """Rejection position 12."""
    if program is None:
        return
    if derive.program_posture(program) == "FROZEN":
        fail("ERR_PROGRAM_FROZEN")


def guard_terminal(row, dimension, terminals):
    if row.get(dimension) in terminals:
        fail("ERR_ALREADY_TERMINAL")


def guard_origin(row, dimension, origins):
    if row.get(dimension) not in origins:
        fail("ERR_TRANSITION_NOT_ALLOWED")


def state_gate(row, dimension, origins, terminals):
    """Positions 10 and 11: terminal first so both errors stay reachable."""
    guard_terminal(row, dimension, terminals)
    guard_origin(row, dimension, origins)


# --------------------------------------------------------------------------- #
# mortgage clearance / regression driven by household readiness
# --------------------------------------------------------------------------- #
def clear_approved_applications(household):
    for application in derive.applications_of_household(household):
        if application.get("status") == "APPROVED":
            application["status"] = "CLEARED_TO_CLOSE"
            bump(application)


def regress_cleared_applications(household):
    for application in derive.applications_of_household(household):
        if application.get("status") == "CLEARED_TO_CLOSE":
            application["status"] = "APPROVED"
            bump(application)


def core_currency_ok(household):
    enrollment = derive.core_enrollment(household)
    if enrollment is None or enrollment.get("status") != "COMPLETED":
        return False
    expires = enrollment.get("expires_on")
    expires_dt = date_start(expires) if isinstance(expires, str) else expires
    if expires_dt is None:
        return False
    return expires_dt > db.now()


def try_advance_to_closing_ready(household):
    """EDUCATION_COMPLETE -> CLOSING_READY when both obligations are met."""
    if household.get("partnership_readiness") != "EDUCATION_COMPLETE":
        return False
    derive.refresh_household(household)
    if not household.get("sweat_equity_satisfied"):
        return False
    if not core_currency_ok(household):
        return False
    household["partnership_readiness"] = "CLOSING_READY"
    bump(household)
    clear_approved_applications(household)
    return True


def regress_from_closing_ready(household):
    """CLOSING_READY -> EDUCATION_COMPLETE after hours fall below requirement."""
    if household.get("partnership_readiness") != "CLOSING_READY":
        return False
    household["partnership_readiness"] = "EDUCATION_COMPLETE"
    bump(household)
    regress_cleared_applications(household)
    return True


def readiness_to_not_ready(household):
    """Education failure / expiry knocks readiness back to NOT_READY."""
    current = household.get("partnership_readiness")
    if current in ("WITHDRAWN", "NOT_READY"):
        return False
    household["partnership_readiness"] = "NOT_READY"
    bump(household)
    regress_cleared_applications(household)
    return True


# --------------------------------------------------------------------------- #
# sweat equity credit cascade
# --------------------------------------------------------------------------- #
def after_credit(household, member):
    derive.refresh_member(member)
    bump(member)
    derive.refresh_household(household)
    if household.get("selection_status") == "SELECTED" and \
            dec(household.get("sweat_equity_credited_hours") or 0) > Decimal(0):
        household["selection_status"] = "PARTNERSHIP_ACTIVE"
    bump(household)
    try_advance_to_closing_ready(household)


def after_reversal(household, member):
    derive.refresh_member(member)
    bump(member)
    derive.refresh_household(household)
    bump(household)
    if not household.get("sweat_equity_satisfied"):
        regress_from_closing_ready(household)


# --------------------------------------------------------------------------- #
# denial cascade
# --------------------------------------------------------------------------- #
def deny_household(household):
    if household.get("partnership_readiness") != "WITHDRAWN":
        household["partnership_readiness"] = "WITHDRAWN"
    for member in derive.members_of_household(household):
        if member.get("status") == "ACTIVE":
            member["status"] = "REMOVED"
            bump(member)
    for enrollment in derive.enrollments_of_household(household):
        if enrollment.get("status") in ("ENROLLED", "IN_PROGRESS"):
            enrollment["status"] = "FAILED"
            bump(enrollment)


# --------------------------------------------------------------------------- #
# construction cascades
# --------------------------------------------------------------------------- #
def release_seat(seat, status="CANCELLED"):
    seat["status"] = status
    bump(seat)
    volunteer_id = seat.get("volunteer_id")
    if volunteer_id:
        volunteer = db.volunteers.get(volunteer_id)
        if volunteer is not None:
            derive.refresh_volunteer(volunteer)
            bump(volunteer)
    return seat


def cancel_shift_seats(shift, statuses=("RESERVED", "CONFIRMED", "CHECKED_IN")):
    for seat in derive.assignments_of_shift(shift):
        if seat["status"] in statuses:
            release_seat(seat, "CANCELLED")


def safety_hold_cascade(site):
    for shift in derive.shifts_of_site(site):
        if shift["status"] in ("SCHEDULED", "OPEN", "LOCKED"):
            shift["status"] = "CANCELLED"
            bump(shift)
            cancel_shift_seats(shift)


def suspend_volunteer_cascade(volunteer):
    """Third strike suspends the profile and drops its future reservations."""
    derive.refresh_volunteer(volunteer)
    if (volunteer.get("no_show_strikes") or 0) < 3:
        return False
    if volunteer.get("status") == "SUSPENDED":
        return False
    volunteer["status"] = "SUSPENDED"
    bump(volunteer)
    now = db.now()
    for seat in derive.assignments_of_volunteer(volunteer):
        if seat["status"] != "RESERVED":
            continue
        shift = derive.shift_of_assignment(seat)
        if shift is None or shift.get("start_at") is None:
            continue
        if shift["start_at"] > now:
            release_seat(seat, "CANCELLED")
    return True


# --------------------------------------------------------------------------- #
# clock cascade
# --------------------------------------------------------------------------- #
def clock_cascade():
    now = db.now()
    # 1. expired homebuyer education
    for enrollment in list(db.enrollments.values()):
        if enrollment.get("status") != "COMPLETED":
            continue
        expires = enrollment.get("expires_on")
        expires_dt = date_start(expires) if isinstance(expires, str) else expires
        if expires_dt is None or now < expires_dt:
            continue
        enrollment["status"] = "EXPIRED"
        bump(enrollment)
        if enrollment.get("curriculum_code") != "HOMEBUYER_CORE":
            continue
        household = db.households.get(enrollment.get("household_id"))
        if household is None:
            continue
        if household.get("partnership_readiness") in ("CLOSING_READY", "EDUCATION_COMPLETE"):
            household["partnership_readiness"] = "NOT_READY"
            bump(household)
            regress_cleared_applications(household)

    # 2. volunteer minor flag
    for volunteer in list(db.volunteers.values()):
        birth = date_start(volunteer.get("birth_date"))
        from util import whole_years_between
        age = whole_years_between(birth, now)
        minor = age is not None and age < 18
        if bool(volunteer.get("is_minor")) != minor:
            volunteer["is_minor"] = minor
            bump(volunteer)

    # 3. forgiveness accrual on live liens
    for application in list(db.applications.values()):
        if calc.refresh_lien(application):
            bump(application)
