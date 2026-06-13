"""Co-employment tenure rollup, escalation, and the assignment's parallel
engagement/compliance dimensions (§3.6, §3.7).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    get_success_data, make_supplier_headers, TEST_USERS,
    create_program, create_supplier, create_worker, create_requisition,
    distribute, create_submittal, set_clock, advance_clock,
    setup_active_assignment,
)
from test_helpers import factories as F

PM = TEST_USERS["program_manager_headers"]
HM = TEST_USERS["hiring_manager_headers"]


def _hire_active_assignment(api, program, start_date, planned_end_date,
                            limit_days=180, warning_days=120, clock_iso=None):
    """Build an ACTIVE assignment in the given program. Returns
    (worker, assignment, supplier_headers)."""
    supplier = create_supplier(program["id"])
    worker = create_worker(program["id"])
    sh = make_supplier_headers(supplier["id"])
    req = create_requisition(program["id"])
    distribute(req["id"], [supplier["id"]])
    sub = create_submittal(req["id"], supplier["id"], worker["id"], pay_rate_cents=8000)
    get_success_data(api.shortlist_submittal(sub["id"], HM))
    get_success_data(api.start_interview(sub["id"], HM))
    get_success_data(api.propose_rate(sub["id"], {"pay_rate_cents": 8000}, sh))
    get_success_data(api.offer_submittal(sub["id"], HM))
    req_now = get_success_data(api.get_requisition(req["id"], PM))
    get_success_data(api.hire_submittal(sub["id"], F.hire_payload(
        req_now["version"], start_date, planned_end_date), PM))
    asg = get_success_data(api.list_assignments(PM, params={"worker_profile_id": worker["id"]}))[0]
    return worker, asg, sh


# ===========================================================================
# Queue A: non_linear_state_machine /
#          assignment_parallel_engagement_and_compliance_dimensions
# ===========================================================================

def test_hold_then_clock_advance_sets_on_hold_and_tenure_warning(api):
    """PRD §3.6: "Placing an assignment on hold moves `engagement_status` from
    `ACTIVE` to `ON_HOLD`"
    PRD §3.7: "An assignment whose engagement has not yet ended escalates as
    tenure climbs: from `CLEAR` to `TENURE_WARNING` once the worker's
    `cumulative_engaged_days` reaches at least `tenure_warning_threshold_days`
    while still below `coemployment_tenure_limit_days`"
    PRD §3.7: "an `ON_HOLD` assignment still accrues calendar tenure"

    Hold (engagement->ON_HOLD), then advance to 2026-04-30 (120 inclusive days):
    compliance->TENURE_WARNING independently; both dimensions set on one row.

    Design: Difficulty/non_linear_state_machine/assignment_parallel_engagement_and_compliance_dimensions
    """
    program = create_program(coemployment_tenure_limit_days=180,
                             tenure_warning_threshold_days=120)
    set_clock(program["id"], "2026-01-01T00:00:00.000Z")
    worker, asg, sh = _hire_active_assignment(
        api, program, "2026-01-01T00:00:00.000Z", "2026-12-01T00:00:00.000Z")
    get_success_data(api.hold_assignment(asg["id"], PM))
    advance_clock(program["id"], "2026-04-30T00:00:00.000Z")
    data = get_success_data(api.get_assignment(asg["id"], PM))
    assert data["engagement_status"] == "ON_HOLD", f"got {data['engagement_status']}"
    assert data["compliance_status"] == "TENURE_WARNING", f"got {data['compliance_status']}"


def test_on_hold_assignment_accrues_cumulative_engaged_days(api):
    """PRD §3.7: "for an assignment that is still `ACTIVE` or `ON_HOLD`, it is the
    number of days from `start_date` through the program's current clock date,
    again counting both endpoints."
    PRD §3.7: "an `ON_HOLD` assignment still accrues calendar tenure — putting a
    worker on hold does not pause the co-employment clock"

    From 2026-01-01 to 2026-04-30 inclusive is 120 days even though the
    assignment is ON_HOLD.

    Design: Difficulty/non_linear_state_machine/assignment_parallel_engagement_and_compliance_dimensions
    """
    program = create_program(coemployment_tenure_limit_days=180,
                             tenure_warning_threshold_days=120)
    set_clock(program["id"], "2026-01-01T00:00:00.000Z")
    worker, asg, sh = _hire_active_assignment(
        api, program, "2026-01-01T00:00:00.000Z", "2026-12-01T00:00:00.000Z")
    get_success_data(api.hold_assignment(asg["id"], PM))
    advance_clock(program["id"], "2026-04-30T00:00:00.000Z")
    w = get_success_data(api.get_worker(worker["id"], PM))
    assert w["cumulative_engaged_days"] == 120, f"got {w['cumulative_engaged_days']}"


# ===========================================================================
# Queue A: compensating_invariant / worker_tenure_days_conserved_across_offboard
# ===========================================================================

def test_offboard_freezes_engaged_days_at_inclusive_count(api):
    """PRD §3.6: "On a successful offboard the system sets `actual_end_date` to
    the current program clock date, freezes `engaged_days` at the inclusive day
    count, and recomputes the worker's tenure via the rollup of §3.7."
    PRD §3.7: "for an assignment whose `engagement_status` is `ENDED`, it is the
    number of days from `start_date` through `actual_end_date` counting both
    endpoints"

    Start 2026-01-01, clock 2026-03-31 at offboard -> engaged_days == 90 and
    actual_end_date == 2026-03-31.

    Design: Difficulty/compensating_invariant/worker_tenure_days_conserved_across_offboard
    """
    program = create_program(coemployment_tenure_limit_days=3650,
                             tenure_warning_threshold_days=3000)
    set_clock(program["id"], "2026-01-01T00:00:00.000Z")
    worker, asg, sh = _hire_active_assignment(
        api, program, "2026-01-01T00:00:00.000Z", "2026-12-01T00:00:00.000Z")
    advance_clock(program["id"], "2026-03-31T00:00:00.000Z")
    data = validate_success(api.offboard_assignment(asg["id"], PM))
    assert data["engaged_days"] == 90, f"got {data['engaged_days']}"
    assert data["actual_end_date"] == "2026-03-31T00:00:00.000Z", f"got {data['actual_end_date']}"


def test_cumulative_engaged_days_equals_sum_of_assignment_days_after_offboard(api):
    """PRD §3.7: "For a given worker it sums `engaged_days` across all of that
    worker's assignments in the program — those that are `ACTIVE`, those that are
    `ON_HOLD`, and those that are `ENDED` alike ... and stores the total in the
    worker's `cumulative_engaged_days`."

    With one assignment of engaged_days 90, the worker's cumulative is exactly 90
    after offboard — no drift.

    Design: Difficulty/compensating_invariant/worker_tenure_days_conserved_across_offboard
    """
    program = create_program(coemployment_tenure_limit_days=3650,
                             tenure_warning_threshold_days=3000)
    set_clock(program["id"], "2026-01-01T00:00:00.000Z")
    worker, asg, sh = _hire_active_assignment(
        api, program, "2026-01-01T00:00:00.000Z", "2026-12-01T00:00:00.000Z")
    advance_clock(program["id"], "2026-03-31T00:00:00.000Z")
    get_success_data(api.offboard_assignment(asg["id"], PM))
    w = get_success_data(api.get_worker(worker["id"], PM))
    assert w["cumulative_engaged_days"] == 90, f"got {w['cumulative_engaged_days']}"


# ===========================================================================
# Queue B: calculations / tenure_breach_skips_warning_on_large_clock_jump
# ===========================================================================

def test_large_clock_jump_breaches_tenure_and_forces_on_hold(api):
    """PRD §3.7: "when the cumulative total goes from below the warning mark
    directly to at or above `coemployment_tenure_limit_days` and the prior
    `compliance_status` was `CLEAR`, the assignment moves directly from `CLEAR`
    to `TENURE_BREACH`, skipping `TENURE_WARNING`."
    PRD §3.7: "at the moment an assignment reaches `TENURE_BREACH`, if its
    `engagement_status` is `ACTIVE` the system forces it to `ON_HOLD`."

    Single advance to 2026-06-29 (180 inclusive days, == limit) from CLEAR ->
    TENURE_BREACH directly, engagement forced ACTIVE->ON_HOLD.

    Design: Corner/calculations/tenure_breach_skips_warning_on_large_clock_jump
    """
    program = create_program(coemployment_tenure_limit_days=180,
                             tenure_warning_threshold_days=120)
    set_clock(program["id"], "2026-01-01T00:00:00.000Z")
    worker, asg, sh = _hire_active_assignment(
        api, program, "2026-01-01T00:00:00.000Z", "2026-12-01T00:00:00.000Z")
    advance_clock(program["id"], "2026-06-29T00:00:00.000Z")
    w = get_success_data(api.get_worker(worker["id"], PM))
    assert w["cumulative_engaged_days"] == 180, f"got {w['cumulative_engaged_days']}"
    data = get_success_data(api.get_assignment(asg["id"], PM))
    assert data["compliance_status"] == "TENURE_BREACH", f"got {data['compliance_status']}"
    assert data["engagement_status"] == "ON_HOLD", f"got {data['engagement_status']}"
