"""Loan default cascade during clock advance and the participant
SUSPENDED <-> ACTIVE auto-revert (PRD §3.5, §3.2, §2.8)."""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    advance_clock,
    request_and_approve_loan,
    setup_participant_with_balance,
    validate_success,
)


# ===========================================================================
# Default cascade — PRD §3.5
# ===========================================================================
def test_loan_defaults_when_grace_period_expires(api):
    """PRD §3.5: "A loan transitions automatically from ACTIVE to
    DEFAULTED during clock-advance whenever the loan's next_due_date
    plus 90 days is earlier than the new current_date and
    outstanding_principal_cents is greater than zero."

    Claim: with origination 2026-01-01 -> next_due=2026-01-31; clock
    advance to 2026-05-15 (> next_due + 90 days = 2026-05-01) flips
    the loan to DEFAULTED.

    # difficulty: non_linear_state_machine/loan_branching_on_default_vs_satisfied
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=4_000_000,
        cliff_years=1,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    loan = request_and_approve_loan(
        plan["id"], p["id"],
        requested_amount_cents=1_000_000, term_months=10,
    )
    assert loan["status"] == "ACTIVE"
    # Advance to a date well past next_due_date + 90 days.  PRD §3.1
    # initializes PlanClock to today's UTC date, so the loan's
    # origination_date and next_due_date are anchored to today; we
    # advance to origination + 365 days so the grace window
    # (next_due + 90 days) is definitively crossed regardless of
    # which calendar date "today" lands on.
    from datetime import date as _date, timedelta as _td
    target = (
        _date.fromisoformat(loan["origination_date"]) + _td(days=365)
    ).isoformat()
    advance_clock(plan["id"], target)
    loan_after = validate_success(
        api.get_loan(
            plan["id"], p["id"], loan["id"],
            TEST_USERS["admin_headers"],
        ),
        200,
    )
    assert loan_after["status"] == "DEFAULTED"


def test_loan_default_cascade_debits_participant_balance(api):
    """PRD §3.5: "The first hop applies a synthetic deemed-distribution
    debit: the participant's total_account_balance_cents is reduced by
    outstanding_principal_cents." and "After both hops, the loan's
    outstanding_principal_cents is set to zero."

    Claim: post-default, participant.total_account_balance_cents is
    debited by the outstanding amount that existed at default time;
    loan.outstanding_principal_cents == 0.

    # difficulty: non_linear_state_machine/loan_branching_on_default_vs_satisfied
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=4_000_000,
        cliff_years=1,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    p_before = validate_success(
        api.get_participant(
            plan["id"], p["id"], TEST_USERS["admin_headers"],
        ),
        200,
    )
    balance_before = p_before["total_account_balance_cents"]
    loan = request_and_approve_loan(
        plan["id"], p["id"],
        requested_amount_cents=1_000_000, term_months=10,
    )
    outstanding_at_default = loan["outstanding_principal_cents"]
    # Anchor advance to origination_date + 365 days so we are reliably past
    # next_due_date + 90 regardless of which real wall-clock date today is
    # (PlanClock initializes to today's UTC date per PRD §3.1; the fixture's
    # starting_clock cannot rewind it).
    from datetime import date as _date, timedelta as _td
    target = (
        _date.fromisoformat(loan["origination_date"]) + _td(days=365)
    ).isoformat()
    advance_clock(plan["id"], target)
    p_after = validate_success(
        api.get_participant(
            plan["id"], p["id"], TEST_USERS["admin_headers"],
        ),
        200,
    )
    loan_after = validate_success(
        api.get_loan(
            plan["id"], p["id"], loan["id"],
            TEST_USERS["admin_headers"],
        ),
        200,
    )
    assert loan_after["status"] == "DEFAULTED"
    assert loan_after["outstanding_principal_cents"] == 0
    assert p_after["total_account_balance_cents"] == (
        balance_before - outstanding_at_default
    )


# ===========================================================================
# Clock-advance revert SUSPENDED -> ACTIVE — PRD §3.2
# ===========================================================================
def test_suspension_lifts_when_clock_passes_deferral_until(api):
    """PRD §3.2: "The second is the system-driven SUSPENDED -> ACTIVE
    transition, which fires automatically during a clock-advance when
    the new current_date is strictly greater than the participant's
    deferral_suspended_until; its side effect is to reset
    deferral_suspended_until to null."

    Claim: a hardship approval suspends; advancing the clock past
    deferral_suspended_until restores ACTIVE with
    deferral_suspended_until == null.

    # difficulty: non_linear_state_machine/participant_branching_active_suspended_terminated
    """
    from test_helpers import request_hardship, approve_hardship
    plan, p = setup_participant_with_balance(
        target_balance_cents=1_000_000,
        cliff_years=1,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    hw = request_hardship(
        plan["id"], p["id"],
        requested_amount_cents=200_000,
        hardship_reason_code="MEDICAL",
    )
    approve_hardship(plan["id"], p["id"], hw["id"])
    # Participant should now be SUSPENDED with
    # deferral_suspended_until = clock + 180 days.
    p_susp = validate_success(
        api.get_participant(
            plan["id"], p["id"], TEST_USERS["admin_headers"],
        ),
        200,
    )
    assert p_susp["status"] == "SUSPENDED"
    suspended_until = p_susp["deferral_suspended_until"]
    assert suspended_until is not None

    # Advance clock past suspended_until.
    from datetime import date as _date, timedelta as _td
    target = (
        _date.fromisoformat(suspended_until) + _td(days=2)
    ).isoformat()
    advance_clock(plan["id"], target)
    p_after = validate_success(
        api.get_participant(
            plan["id"], p["id"], TEST_USERS["admin_headers"],
        ),
        200,
    )
    assert p_after["status"] == "ACTIVE"
    assert p_after["deferral_suspended_until"] is None


def test_suspension_lifts_clock_revert_second_case(api):
    """PRD §3.2: same auto-revert rule — second test for the
    participant-branching difficulty instance.

    # difficulty: non_linear_state_machine/participant_branching_active_suspended_terminated
    """
    from test_helpers import request_hardship, approve_hardship
    plan, p = setup_participant_with_balance(
        target_balance_cents=800_000,
        cliff_years=1,
        starting_clock="2026-03-01", hire_date="2020-05-15",
    )
    hw = request_hardship(
        plan["id"], p["id"],
        requested_amount_cents=100_000,
        hardship_reason_code="FUNERAL",
    )
    approve_hardship(plan["id"], p["id"], hw["id"])
    p_susp = validate_success(
        api.get_participant(
            plan["id"], p["id"], TEST_USERS["admin_headers"],
        ),
        200,
    )
    assert p_susp["status"] == "SUSPENDED"
    suspended_until = p_susp["deferral_suspended_until"]
    from datetime import date as _date, timedelta as _td
    target = (
        _date.fromisoformat(suspended_until) + _td(days=1)
    ).isoformat()
    advance_clock(plan["id"], target)
    p_after = validate_success(
        api.get_participant(
            plan["id"], p["id"], TEST_USERS["admin_headers"],
        ),
        200,
    )
    assert p_after["status"] == "ACTIVE"
    assert p_after["deferral_suspended_until"] is None
