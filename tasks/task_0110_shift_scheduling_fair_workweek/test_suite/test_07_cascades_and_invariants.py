"""No-show strike cascade, locked-pay-period gate, and assign/cancel conservation.

Covers Difficulty: transitive_cascade (no-show depth-2 strike->suspend),
cross_entity_state_dependency (cancel blocked by LOCKED pay-period),
compensating_invariant (projected-cost and headcount conservation).
Covers Corner state_machines: lock-with-open-assignment.
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    ApiErrorId, make_manager_headers, set_clock, setup_location, setup_worker,
    setup_pay_period, create_posted_shift, assign_worker,
    setup_worker_with_strikes,
)


M = make_manager_headers()


def test_third_noshow_increments_strikes_and_suspends_worker(api):
    """PRD §3.6: "A no-show moves the assignment to NO_SHOW and triggers a
    cross-entity cascade: the worker's no_show_strikes is increased by one, and if
    that brings the count to three the worker's status becomes SUSPENDED."

    Two prior strikes plus a third no-show drives no_show_strikes to 3 and flips the
    worker's status to SUSPENDED (depth-2 chain: increment -> suspend).

    Design: Difficulty/transitive_cascade/noshow_cascade_depth2_strike_suspends_worker
    """
    loc, worker, pp = setup_worker_with_strikes(3, worker_overrides=dict(
        full_name="W", email="w@x.com", base_hourly_rate_cents=2000), api=api)
    assert worker["no_show_strikes"] == 3
    assert worker["status"] == "SUSPENDED"


def test_two_noshows_keep_worker_active_below_ceiling(api):
    """PRD §3.6: "the worker's no_show_strikes is increased by one, and if that brings
    the count to three the worker's status becomes SUSPENDED."
    PRD §3.1: "When it reaches three, the worker's status is automatically set to
    SUSPENDED."

    Boundary partner: at two strikes the worker is one below the ceiling, so
    no_show_strikes is 2 and status remains ACTIVE.

    Design: Difficulty/transitive_cascade/noshow_cascade_depth2_strike_suspends_worker
    """
    loc, worker, pp = setup_worker_with_strikes(2, worker_overrides=dict(
        full_name="W", email="w@x.com", base_hourly_rate_cents=2000), api=api)
    assert worker["no_show_strikes"] == 2
    assert worker["status"] == "ACTIVE"


def test_cancel_assignment_in_locked_payperiod_rejected(api):
    """PRD §3.6: "A manager cancels an individual assignment, permitted only from
    SCHEDULED or CONFIRMED (otherwise ERR_INVALID_ASSIGNMENT_STATE) and only while the
    assignment's pay-period is OPEN (otherwise ERR_PAY_PERIOD_LOCKED)."
    PRD §3.13: "Once locked, any further assignment mutation in the window —
    assigning, cancelling, awarding, or marking a no-show — is refused with
    ERR_PAY_PERIOD_LOCKED."

    An assignment whose pay-period is LOCKED cannot be cancelled. Because the
    assignment was completed (terminal) so the period could lock, two PRD
    sentences govern the same request and §2.7 does not uniquely order them
    against each other: §3.13 ("Once locked, any further assignment mutation in
    the window ... is refused with ERR_PAY_PERIOD_LOCKED") admits the locked
    reading, while §2.7's "state-machine preconditions ... followed by the
    pay-period-open check" admits ERR_INVALID_ASSIGNMENT_STATE for the terminal
    assignment. A faithful PRD-only implementer may produce either, so the
    assertion accepts either member.

    Design: Difficulty/cross_entity_state_dependency/assignment_cancel_blocked_by_locked_payperiod
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    pp = setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                          end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-02T09:00:00Z",
                            end_utc="2026-06-02T13:00:00Z", headcount_required=1)
    asg = assign_worker(api, loc["id"], s["id"], worker["id"])
    # Drive the assignment terminal (complete) so the pay-period can lock.
    set_clock(api, "2026-06-02T13:00:01Z")
    get_success_data(api.complete_shift(loc["id"], s["id"], M))
    get_success_data(api.lock_pay_period(loc["id"], pp["id"], M))
    resp = api.cancel_assignment(loc["id"], asg["id"], M)
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_PAY_PERIOD_LOCKED.value,
        ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE.value,
    ])


def test_cancel_assignment_in_open_payperiod_succeeds(api):
    """PRD §3.6: "A manager cancels an individual assignment, permitted only from
    SCHEDULED or CONFIRMED (otherwise ERR_INVALID_ASSIGNMENT_STATE) and only while the
    assignment's pay-period is OPEN (otherwise ERR_PAY_PERIOD_LOCKED). Cancellation
    moves the assignment to CANCELLED."

    Boundary partner: with the same SCHEDULED assignment but its pay-period still
    OPEN, the cancel is permitted and the assignment moves to CANCELLED. This pins
    the LOCKED state — not the assignment's own state — as the gate the sibling test
    triggers.

    Design: Difficulty/cross_entity_state_dependency/assignment_cancel_blocked_by_locked_payperiod
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-05T09:00:00Z",
                            end_utc="2026-06-05T13:00:00Z", headcount_required=1)
    asg = assign_worker(api, loc["id"], s["id"], worker["id"])
    data = get_success_data(api.cancel_assignment(loc["id"], asg["id"], M))
    assert data["status"] == "CANCELLED"


def test_lock_payperiod_with_open_assignment_rejected(api):
    """PRD §3.13: "A manager locks a pay-period, permitted only from OPEN (otherwise
    ERR_PAY_PERIOD_LOCKED), and only when every assignment whose pay-period is this
    one is already in a terminal state — COMPLETED, NO_SHOW, or CANCELLED (otherwise
    ERR_OPEN_ASSIGNMENTS_EXIST)."

    Locking a pay-period that still has a SCHEDULED (non-terminal) assignment ->
    ERR_OPEN_ASSIGNMENTS_EXIST.

    Design: Corner/state_machines/lock_payperiod_with_open_assignment_returns_open_assignments_exist
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    pp = setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                          end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-05T09:00:00Z",
                            end_utc="2026-06-05T13:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], s["id"], worker["id"])
    resp = api.lock_pay_period(loc["id"], pp["id"], M)
    validate_error(resp, ApiErrorId.ERR_OPEN_ASSIGNMENTS_EXIST.value)


def test_assign_then_cancel_conserves_projected_cost(api):
    """PRD §3.10: "A pay-period exposes its projected_labor_cost_cents as a read-only
    field reconciled on every assignment or ledger change."
    PRD §3.6: "Cancellation moves the assignment to CANCELLED, removes it from the
    filled set so the parent shift may bubble down from FULLY_STAFFED to OPEN, and
    reconciles the pay-period to remove the assignment's provisional cost."

    Conserved quantity = projected_labor_cost_cents: assigning a worker (projected
    0 -> 16000) then cancelling (removes exactly that provisional cost) returns
    projected to its pre-assignment value of 0.

    Design: Difficulty/compensating_invariant/assign_then_cancel_conserves_projected_cost
    """
    set_clock(api, "2026-05-30T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    pp = setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                          end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-02T09:00:00Z",
                            end_utc="2026-06-02T17:00:00Z", headcount_required=1)
    asg = assign_worker(api, loc["id"], s["id"], worker["id"])
    mid = get_success_data(api.get_pay_period(pp["id"], M))
    assert mid["projected_labor_cost_cents"] == 16000, "projected after assign"
    get_success_data(api.cancel_assignment(loc["id"], asg["id"], M))
    asg = get_success_data(api.get_assignment(asg["id"], M))
    assert asg["status"] == "CANCELLED"
    pp_data = get_success_data(api.get_pay_period(pp["id"], M))
    assert pp_data["projected_labor_cost_cents"] == 0, "projected restored to 0 after cancel"


def test_assign_then_cancel_conserves_headcount_filled(api):
    """PRD §2.10: "When an assignment enters the filled set and that makes the shift
    fully staffed, the shift auto-advances from OPEN to FULLY_STAFFED with no explicit
    request on the shift. When an assignment later leaves the filled set — through
    cancellation or a no-show — and the filled count drops below the required count,
    the shift reverts from FULLY_STAFFED back to OPEN so the seat can be re-staffed."

    Conserved quantity = headcount_filled: assigning (0->1, OPEN->FULLY_STAFFED) then
    cancelling (1->0, FULLY_STAFFED->OPEN) restores headcount_filled to 0 and the
    shift to OPEN.

    Design: Difficulty/compensating_invariant/assign_then_cancel_conserves_headcount_filled
    """
    set_clock(api, "2026-05-30T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-02T09:00:00Z",
                            end_utc="2026-06-02T13:00:00Z", headcount_required=1)
    asg = assign_worker(api, loc["id"], s["id"], worker["id"])
    mid = get_success_data(api.get_shift(s["id"], M))
    assert mid["status"] == "FULLY_STAFFED" and mid["headcount_filled"] == 1
    get_success_data(api.cancel_assignment(loc["id"], asg["id"], M))
    shift = get_success_data(api.get_shift(s["id"], M))
    assert shift["headcount_filled"] == 0
    assert shift["status"] == "OPEN"


def test_cancel_one_of_two_conserves_projected_cost_remainder(api):
    """PRD §3.10: "A pay-period exposes its projected_labor_cost_cents as a read-only
    field reconciled on every assignment or ledger change."
    PRD §3.6: "Cancellation moves the assignment to CANCELLED, removes it from the
    filled set so the parent shift may bubble down from FULLY_STAFFED to OPEN, and
    reconciles the pay-period to remove the assignment's provisional cost."

    Conservation with a non-zero remainder: two 8h assignments (projected 32000);
    cancelling exactly one removes exactly that 16000 of provisional cost, leaving
    projected at the surviving assignment's 16000.

    Design: Difficulty/compensating_invariant/assign_then_cancel_conserves_projected_cost
    """
    set_clock(api, "2026-05-30T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    pp = setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                          end_utc="2026-06-08T00:00:00Z")
    sa = create_posted_shift(api, loc["id"], start_utc="2026-06-02T09:00:00Z",
                             end_utc="2026-06-02T17:00:00Z", headcount_required=1)
    a1 = assign_worker(api, loc["id"], sa["id"], worker["id"])
    sb = create_posted_shift(api, loc["id"], start_utc="2026-06-03T09:00:00Z",
                             end_utc="2026-06-03T17:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], sb["id"], worker["id"])
    both = get_success_data(api.get_pay_period(pp["id"], M))
    assert both["projected_labor_cost_cents"] == 32000, "projected with both assignments"
    get_success_data(api.cancel_assignment(loc["id"], a1["id"], M))
    pp_data = get_success_data(api.get_pay_period(pp["id"], M))
    assert pp_data["projected_labor_cost_cents"] == 16000, (
        f"projected should drop by exactly the cancelled 16000, got "
        f"{pp_data['projected_labor_cost_cents']}")


def test_cancel_one_of_two_seats_conserves_headcount_filled_remainder(api):
    """PRD §2.10: "When an assignment later leaves the filled set — through
    cancellation or a no-show — and the filled count drops below the required count,
    the shift reverts from FULLY_STAFFED back to OPEN so the seat can be re-staffed.
    The filled set for a shift is precisely its assignments in SCHEDULED, CONFIRMED,
    or COMPLETED."

    Conservation with a non-zero remainder: a two-seat shift filled by two workers is
    FULLY_STAFFED with headcount_filled 2; cancelling one assignment drops
    headcount_filled to exactly 1 and reverts the shift to OPEN.

    Design: Difficulty/compensating_invariant/assign_then_cancel_conserves_headcount_filled
    """
    set_clock(api, "2026-05-30T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    w1 = setup_worker(api, loc["id"], full_name="W1", email="w1@x.com", base_hourly_rate_cents=2000)
    w2 = setup_worker(api, loc["id"], full_name="W2", email="w2@x.com", base_hourly_rate_cents=2000)
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-02T09:00:00Z",
                            end_utc="2026-06-02T13:00:00Z", headcount_required=2)
    a1 = assign_worker(api, loc["id"], s["id"], w1["id"])
    assign_worker(api, loc["id"], s["id"], w2["id"])
    full = get_success_data(api.get_shift(s["id"], M))
    assert full["status"] == "FULLY_STAFFED" and full["headcount_filled"] == 2
    get_success_data(api.cancel_assignment(loc["id"], a1["id"], M))
    shift = get_success_data(api.get_shift(s["id"], M))
    assert shift["headcount_filled"] == 1
    assert shift["status"] == "OPEN"
