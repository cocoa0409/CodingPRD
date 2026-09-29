"""Shared transition cascades (PRD sections 2.7, 3.4, 3.5, 3.6, 3.7, 3.9)."""

import calc
import derive
from store import clock_now, db, touch


# --------------------------------------------------------------------------
# staff assignment cascades
# --------------------------------------------------------------------------

def release_assignment(assignment, program):
    """PROPOSED | CONFIRMED -> RELEASED, with asymmetric bookkeeping."""
    if assignment["status"] not in ("PROPOSED", "CONFIRMED"):
        return False
    was_confirmed = assignment["status"] == "CONFIRMED"
    assignment["status"] = "RELEASED"
    touch(assignment)
    if was_confirmed and program is not None:
        # confirmed_minutes_total is derived from the assignment set, so the
        # decrement happens implicitly; the gap counter is monotonic.
        program["staffing_gap_count"] += 1
    return True


def release_assignments_of_element(element, program):
    for assignment in derive.assignments_of_element(element["id"]):
        release_assignment(assignment, program)


def release_assignments_of_segment(segment, program):
    for assignment in derive.assignments_of_segment(segment["id"]):
        release_assignment(assignment, program)


def complete_assignment(assignment, staff_member=None):
    """CHECKED_IN -> COMPLETED, running the ACTUAL labour-cost variant."""
    if assignment["status"] != "CHECKED_IN":
        return False
    member = staff_member or db.staff_members.get(assignment["staff_id"])
    assignment["status"] = "COMPLETED"
    assignment["completed_at"] = clock_now()
    minutes = calc.actual_minutes(assignment)
    rate = member["pay_rate_cents_per_hour"] if member else 0
    assignment["actual_labor_cost_cents"] = calc.staff_labor_cost(minutes, rate)
    touch(assignment)
    return True


def no_show_assignment(assignment, program):
    """CONFIRMED -> NO_SHOW."""
    if assignment["status"] != "CONFIRMED":
        return False
    assignment["status"] = "NO_SHOW"
    assignment["actual_labor_cost_cents"] = 0
    touch(assignment)
    if program is not None:
        program["staffing_gap_count"] += 1
    return True


def settle_staffing_on_delivery(element, program):
    """Two symmetric branches at element delivery / segment departure."""
    for assignment in derive.assignments_of_element(element["id"]):
        if assignment["status"] == "CHECKED_IN":
            complete_assignment(assignment)
    for assignment in derive.assignments_of_element(element["id"]):
        if assignment["status"] == "CONFIRMED":
            no_show_assignment(assignment, program)


# --------------------------------------------------------------------------
# program bubble-up
# --------------------------------------------------------------------------

def bubble_program_completed(program):
    """IN_EXECUTION -> COMPLETED once no open element remains."""
    if program["execution_status"] != "IN_EXECUTION":
        return False
    if derive.open_element_count(program["id"]) != 0:
        return False
    program["execution_status"] = "COMPLETED"
    touch(program)
    return True


def close_active_contracts(program):
    for contract in derive.contracts_of_program(program["id"]):
        if contract["status"] == "ACTIVE":
            contract["status"] = "CLOSED"
            touch(contract)


def bubble_program_settled(program):
    """CLIENT_INVOICED -> SETTLED on release with nothing open."""
    if program["settlement_status"] != "CLIENT_INVOICED":
        return False
    if derive.supplier_open_payable_cents(program["id"]) != 0:
        return False
    if not any(p["status"] == "PAID" for p in derive.payments_of_program(program["id"])):
        return False
    program["settlement_status"] = "SETTLED"
    close_active_contracts(program)
    touch(program)
    return True


# --------------------------------------------------------------------------
# element cancellation
# --------------------------------------------------------------------------

def cancel_element(element, program, bubble=True):
    """PLANNED | PERMIT_BLOCKED | READY -> CANCELLED with penalty and staff release."""
    if element["status"] not in ("PLANNED", "PERMIT_BLOCKED", "READY"):
        return False
    element["status"] = "CANCELLED"
    tier = derive.cancellation_tier_for(element)
    element["cancellation_penalty_cents"] = calc.cancellation_penalty(element, tier)
    touch(element)
    release_assignments_of_element(element, program)
    if bubble:
        bubble_program_completed(program)
    return True


def block_element(element, program):
    """PLANNED | READY -> PERMIT_BLOCKED with the staff-release cascade."""
    if element["status"] not in ("PLANNED", "READY"):
        return False
    element["status"] = "PERMIT_BLOCKED"
    touch(element)
    release_assignments_of_element(element, program)
    return True


# --------------------------------------------------------------------------
# transport segment cancellation / departure
# --------------------------------------------------------------------------

def cancel_segment(segment, program, bubble=True):
    """SCHEDULED -> CANCELLED, releasing the manifest and the shifts."""
    if segment["status"] != "SCHEDULED":
        return False
    segment["status"] = "CANCELLED"
    for entry in derive.entries_of_segment(segment["id"]):
        if entry["status"] in ("ASSIGNED", "CHECKED_IN"):
            entry["status"] = "RELEASED"
            touch(entry)
            if program is not None:
                program["unseated_guest_count"] += 1
    release_assignments_of_segment(segment, program)
    touch(segment)
    return True
