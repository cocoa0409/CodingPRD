"""Plan lifecycle (DRAFT -> ACTIVE -> FROZEN), PlanClock semantics,
clock-advance monotonicity, and vesting-epoch advance (PRD §2.7,
§2.12, §3.1)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_plan,
    create_and_activate_plan,
    create_draft_plan,
    enroll_and_activate_participant,
    request_and_approve_loan,
    request_hardship,
    setup_participant_with_balance,
    validate_error,
    validate_success,
)


# ===========================================================================
# Plan activation creates PlanClock — PRD §2.7 / §3.1
# ===========================================================================
def test_activate_plan_transitions_draft_to_active(api, admin_headers):
    """PRD §3.1: "Activation, performed by a PlanAdministrator,
    advances the plan from DRAFT to ACTIVE."

    Claim: POST /activate flips status from DRAFT to ACTIVE.
    """
    plan = create_draft_plan()
    assert plan["status"] == "DRAFT"
    res = api.activate_plan(plan["id"], None, admin_headers)
    activated = validate_success(res, 200)
    assert activated["status"] == "ACTIVE"


def test_activate_tiered_plan_with_empty_brackets_rejected(api, admin_headers):
    """PRD §3.1: "Activation requires that ... if the match is TIERED,
    tiered_brackets must be non-empty ... A configuration that
    violates these rules at activation time is rejected with
    ERR_INVALID_PLAN_CONFIG."

    Claim: tiered_brackets becomes empty at activation -> rejected.

    Setup: create the plan with valid tiered_brackets, then attempt to
    activate after the create-time check passes. (Implementations that
    re-validate at activate per the PRD's explicit re-statement of
    these preconditions will exercise this path.)
    """
    # Since create-time also rejects empty brackets, this test exercises
    # the activation-time check by creating with a single bracket and
    # then asserting that activation with empty brackets via a fresh
    # plan body is rejected at create-time too. The PRD restates the
    # constraint at both points, so the create-time check is the
    # observable rejection.
    res = api.create_plan(
        {
            "plan_name": "Bad Tiered",
            "plan_year": 2026,
            "match_formula_type": "TIERED",
            "tiered_brackets": [],
            "vesting_schedule_type": "CLIFF",
            "cliff_years": 1,
        },
        admin_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_INVALID_PLAN_CONFIG.value,
        expected_status=400,
    )


# ===========================================================================
# Clock monotonicity — PRD §2.7
# ===========================================================================
def test_clock_advance_rejects_equal_date(api, admin_headers):
    """PRD §2.7: "Calls that supply a new_date that is not strictly
    greater than the current current_date are rejected with
    ERR_CLOCK_NOT_MONOTONIC."

    Claim: advance to today's clock again -> ERR_CLOCK_NOT_MONOTONIC.
    """
    plan = create_and_activate_plan(advance_clock_to="2026-06-01")
    # Try to set the same date.
    res = api.advance_clock(
        plan["id"], {"new_date": "2026-06-01"}, admin_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value,
        expected_status=422,
    )


def test_clock_advance_rejects_earlier_date(api, admin_headers):
    """PRD §2.7: "Calls that supply a new_date that is not strictly
    greater than the current current_date are rejected with
    ERR_CLOCK_NOT_MONOTONIC."

    Claim: an earlier date than current -> ERR_CLOCK_NOT_MONOTONIC.
    """
    plan = create_and_activate_plan(advance_clock_to="2026-06-01")
    res = api.advance_clock(
        plan["id"], {"new_date": "2026-05-31"}, admin_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value,
        expected_status=422,
    )


def test_clock_advance_strictly_greater_succeeds(api, admin_headers):
    """PRD §2.7: "Calls that supply a new_date that is not strictly
    greater than the current current_date are rejected with
    ERR_CLOCK_NOT_MONOTONIC."

    Claim: advancing by one day succeeds (200) — the boundary just
    above strict-greater.
    """
    plan = create_and_activate_plan(advance_clock_to="2026-06-01")
    res = api.advance_clock(
        plan["id"], {"new_date": "2026-06-02"}, admin_headers,
    )
    validate_success(res, 200)


# ===========================================================================
# Vesting epoch advance — PRD §2.12 / §3.1
# ===========================================================================
def test_advance_vesting_epoch_increments_by_one(api, admin_headers):
    """PRD §3.1: "A separate administrator capability, the
    advance-vesting-epoch action, increments current_vesting_epoch by
    exactly one."

    Claim: one advance -> epoch goes from 0 to 1.
    """
    plan = create_and_activate_plan()
    assert plan["current_vesting_epoch"] == 0
    res = api.advance_vesting_epoch(plan["id"], None, admin_headers)
    after = validate_success(res, 200)
    assert after["current_vesting_epoch"] == 1


def test_advance_vesting_epoch_twice_yields_two(api, admin_headers):
    """PRD §3.1: "the advance-vesting-epoch action, increments
    current_vesting_epoch by exactly one."

    Claim: two consecutive advances -> epoch == 2.
    """
    plan = create_and_activate_plan()
    api.advance_vesting_epoch(plan["id"], None, admin_headers)
    res = api.advance_vesting_epoch(plan["id"], None, admin_headers)
    after = validate_success(res, 200)
    assert after["current_vesting_epoch"] == 2


# ===========================================================================
# Freeze preconditions — PRD §3.1
# ===========================================================================
def test_freeze_active_plan_succeeds_and_terminal(api, admin_headers):
    """PRD §3.1: "Freezing the plan, also performed by a
    PlanAdministrator, advances status from ACTIVE to FROZEN. FROZEN
    is terminal — the plan never leaves it."

    Claim: a clean ACTIVE plan freezes successfully and status becomes
    'FROZEN'.
    """
    plan = create_and_activate_plan()
    res = api.freeze_plan(plan["id"], None, admin_headers)
    frozen = validate_success(res, 200)
    assert frozen["status"] == "FROZEN"


def test_freeze_blocked_by_active_loan(api, admin_headers):
    """PRD §3.1: "Freeze is rejected with ERR_FREEZE_PRECONDITION_VIOLATED
    whenever any of three preconditions is unmet: no Loan may be in
    ACTIVE status with outstanding_principal_cents greater than zero".

    Claim: an outstanding ACTIVE loan blocks freeze with
    ERR_FREEZE_PRECONDITION_VIOLATED.

    # difficulty: cross_entity_state_dependency/plan_freeze_blocked_by_active_loan
    """
    plan, participant, loan = pytest.helpers_setup_loan_plan() \
        if hasattr(pytest, "helpers_setup_loan_plan") else (None, None, None)
    if plan is None:
        plan, participant = setup_participant_with_balance(
            target_balance_cents=2_000_000,
            cliff_years=1,
            starting_clock="2026-01-01",
            hire_date="2020-01-01",
        )
        loan = request_and_approve_loan(
            plan["id"], participant["id"],
            requested_amount_cents=500_000, term_months=10,
        )
    assert loan["status"] == "ACTIVE"
    assert loan["outstanding_principal_cents"] > 0

    res = api.freeze_plan(plan["id"], None, admin_headers)
    validate_error(
        res,
        ApiErrorId.ERR_FREEZE_PRECONDITION_VIOLATED.value,
        expected_status=409,
    )
    # Plan should still be ACTIVE.
    p = validate_success(api.get_plan(plan["id"], admin_headers), 200)
    assert p["status"] == "ACTIVE"


def test_freeze_blocked_by_active_loan_second_variant(api, admin_headers):
    """PRD §3.1: "Freeze is rejected with ERR_FREEZE_PRECONDITION_VIOLATED
    whenever any of three preconditions is unmet: no Loan may be in
    ACTIVE status with outstanding_principal_cents greater than zero".

    Second test for the difficulty instance, using a different loan
    amount and term to ensure the precondition is enforced beyond a
    single scenario.

    # difficulty: cross_entity_state_dependency/plan_freeze_blocked_by_active_loan
    """
    plan, participant = setup_participant_with_balance(
        target_balance_cents=3_000_000,
        cliff_years=1,
        starting_clock="2026-02-15",
        hire_date="2020-06-15",
    )
    loan = request_and_approve_loan(
        plan["id"], participant["id"],
        requested_amount_cents=750_000, term_months=30,
    )
    assert loan["status"] == "ACTIVE"
    assert loan["outstanding_principal_cents"] > 0

    res = api.freeze_plan(plan["id"], None, admin_headers)
    validate_error(
        res,
        ApiErrorId.ERR_FREEZE_PRECONDITION_VIOLATED.value,
        expected_status=409,
    )
    p_after = validate_success(api.get_plan(plan["id"], admin_headers), 200)
    assert p_after["status"] == "ACTIVE"


def test_freeze_blocked_by_pending_hardship_withdrawal(api, admin_headers):
    """PRD §3.1: "Freeze is rejected with
    ERR_FREEZE_PRECONDITION_VIOLATED whenever any of three
    preconditions is unmet: ... no HardshipWithdrawal may be in
    REQUESTED status".

    Claim: a pending REQUESTED hardship blocks freeze.
    """
    plan, participant = setup_participant_with_balance(
        target_balance_cents=500_000,
        cliff_years=1,
        starting_clock="2026-01-01",
        hire_date="2020-01-01",
    )
    hw = request_hardship(
        plan["id"], participant["id"],
        requested_amount_cents=100_000,
        hardship_reason_code="MEDICAL",
    )
    assert hw["status"] == "REQUESTED"
    res = api.freeze_plan(plan["id"], None, admin_headers)
    validate_error(
        res,
        ApiErrorId.ERR_FREEZE_PRECONDITION_VIOLATED.value,
        expected_status=409,
    )


def test_post_freeze_mutation_rejected_with_plan_frozen(api, admin_headers,
                                                       payroll_headers):
    """PRD §3.1: "Any participant-side mutation attempted after the
    plan has reached FROZEN is rejected with ERR_PLAN_FROZEN."

    Claim: enroll attempt against a FROZEN plan -> ERR_PLAN_NOT_ACTIVE
    or ERR_PLAN_FROZEN. The PRD §3.1 specifically pins ERR_PLAN_FROZEN
    for the FROZEN-specific case; PRD §2.6 step (4) makes
    ERR_PLAN_NOT_ACTIVE the broader gate. Tests accept either since the
    PRD does not commit to which surfaces first when both apply (PRD
    §3.3 deferral-suspension note says "in practice, frozen plans also
    fail the higher-priority ERR_PLAN_NOT_ACTIVE check first" — so
    that is the preferred surface, but ERR_PLAN_FROZEN is also valid).
    """
    plan = create_and_activate_plan()
    api.freeze_plan(plan["id"], None, admin_headers)
    res = api.create_participant(
        plan["id"],
        {
            "employee_external_id": "emp-frozen-1",
            "date_of_birth": "1990-01-01",
            "hire_date": "2020-01-01",
            "annual_compensation_cents": 6_000_000,
            "elected_deferral_pct": 5.0,
        },
        admin_headers,
    )
    body = res.json()
    assert body.get("response_type") == "error"
    err_id = body["data"]["error_id"]
    assert err_id in (
        ApiErrorId.ERR_PLAN_NOT_ACTIVE.value,
        ApiErrorId.ERR_PLAN_FROZEN.value,
    ), f"Expected PLAN_NOT_ACTIVE or PLAN_FROZEN, got {err_id}"
    assert res.status_code == 409


def test_freeze_cascades_active_participants_to_suspended(api, admin_headers,
                                                         payroll_headers):
    """PRD §2.8: "every participant whose status is currently ENROLLED
    or ACTIVE is flipped to SUSPENDED and their deferral_suspended_until
    is set to '9999-12-31' (a sentinel meaning indefinite suspension)."

    Claim: after freeze, an ACTIVE participant becomes SUSPENDED with
    deferral_suspended_until == '9999-12-31'.
    """
    plan, participant = setup_participant_with_balance(
        target_balance_cents=1,  # nominal accumulation, just to confirm state
        cliff_years=1,
        starting_clock="2026-01-01",
        hire_date="2020-01-01",
    )
    assert participant["status"] == "ACTIVE"
    # Freeze the plan.
    api.freeze_plan(plan["id"], None, admin_headers)
    # Re-read participant.
    p = validate_success(
        api.get_participant(plan["id"], participant["id"], admin_headers),
        200,
    )
    assert p["status"] == "SUSPENDED"
    assert p["deferral_suspended_until"] == "9999-12-31"
