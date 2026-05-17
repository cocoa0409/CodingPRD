"""Participant enrollment, activation, deferral updates, and
termination (PRD §3.2 / §2.5)."""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_participant,
    create_and_activate_plan,
    create_draft_plan,
    create_participant_payload,
    enroll_and_activate_participant,
    enroll_participant,
    make_participant_headers,
    request_and_approve_loan,
    setup_basic_active_participant,
    setup_participant_with_balance,
    update_deferral_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Enrollment requires active plan — PRD §2.6 step (4) + §3.2
# ===========================================================================
def test_enroll_into_draft_plan_rejected_plan_not_active(api, admin_headers):
    """PRD §2.6: "the plan-level state gate (the parent Plan must be
    in ACTIVE status for any participant-side mutation — enrollment,
    participant activation, ...), returning ERR_PLAN_NOT_ACTIVE".

    Claim: enrollment under a DRAFT plan -> ERR_PLAN_NOT_ACTIVE.
    """
    plan = create_draft_plan()
    res = api.create_participant(
        plan["id"], create_participant_payload(), admin_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_PLAN_NOT_ACTIVE.value,
        expected_status=409,
    )


def test_enroll_initial_state_and_zero_balances(api, admin_headers):
    """PRD §3.2: "The newly enrolled participant has status of
    ENROLLED, with the computed fields deferral_suspended_until
    initialized to null, vested_pct_snapshot initialized to zero,
    vesting_epoch_at_snapshot initialized to zero,
    cumulative_employee_contribution_cents initialized to zero,
    cumulative_employer_match_cents initialized to zero, and
    total_account_balance_cents initialized to zero."

    Claim: fresh participant carries the exact zero-valued initial
    fields PRD §3.2 specifies.
    """
    plan = create_and_activate_plan()
    res = api.create_participant(
        plan["id"], create_participant_payload(), admin_headers,
    )
    p = validate_success(res, 201)
    assert_participant(p)
    assert p["status"] == "ENROLLED"
    assert p["deferral_suspended_until"] is None
    assert p["vested_pct_snapshot"] == 0 or p["vested_pct_snapshot"] == 0.0
    assert p["vesting_epoch_at_snapshot"] == 0
    assert p["cumulative_employee_contribution_cents"] == 0
    assert p["cumulative_employer_match_cents"] == 0
    assert p["total_account_balance_cents"] == 0


def test_activate_participant_enrolled_to_active(api, admin_headers,
                                                 payroll_headers):
    """PRD §3.2: "A PayrollProcessor activates the enrolled participant,
    transitioning status from ENROLLED to ACTIVE."

    Claim: ENROLLED + activate -> ACTIVE.
    """
    plan = create_and_activate_plan()
    p = enroll_participant(plan["id"])
    assert p["status"] == "ENROLLED"
    res = api.activate_participant(
        plan["id"], p["id"], None, payroll_headers,
    )
    activated = validate_success(res, 200)
    assert activated["status"] == "ACTIVE"


def test_activate_participant_requires_payroll_role(api, admin_headers):
    """PRD §4: POST .../activate authorized only for PayrollProcessor.

    PRD §2.1: "A request that presents valid headers but invokes an
    endpoint the role is not authorized to use is rejected with
    ERR_INSUFFICIENT_PERMISSIONS."

    Claim: activate by PlanAdministrator -> ERR_INSUFFICIENT_PERMISSIONS.
    """
    plan = create_and_activate_plan()
    p = enroll_participant(plan["id"])
    res = api.activate_participant(
        plan["id"], p["id"], None, admin_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
        expected_status=403,
    )


# ===========================================================================
# Path-validation ordering — PRD §2.5
# ===========================================================================
def test_nonexistent_participant_under_existing_plan_returns_participant_not_found(
    api, admin_headers,
):
    """PRD §2.5: "The first identifier that does not resolve to an
    existing resource determines the rejection code: ERR_PLAN_NOT_FOUND,
    ERR_PARTICIPANT_NOT_FOUND".

    Claim: real plan id + fake participant id -> ERR_PARTICIPANT_NOT_FOUND.
    """
    plan = create_and_activate_plan()
    res = api.get_participant(plan["id"], NON_EXISTENT_UUID, admin_headers)
    validate_error(
        res,
        ApiErrorId.ERR_PARTICIPANT_NOT_FOUND.value,
        expected_status=404,
    )


def test_nonexistent_plan_with_nonexistent_participant_returns_plan_not_found(
    api, admin_headers,
):
    """PRD §2.5: "A non-existent participant under a non-existent plan
    must surface as ERR_PLAN_NOT_FOUND, not as ERR_PARTICIPANT_NOT_FOUND."

    Claim: fake plan id + fake participant id -> ERR_PLAN_NOT_FOUND.
    """
    res = api.get_participant(
        NON_EXISTENT_UUID, NON_EXISTENT_UUID, admin_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_PLAN_NOT_FOUND.value,
        expected_status=404,
    )


# ===========================================================================
# Deferral updates — PRD §3.2
# ===========================================================================
def test_deferral_update_invalid_pct_rejected(api, payroll_headers):
    """PRD §3.2: "The new value must be in the range zero through one
    hundred inclusive; otherwise the request is rejected with
    ERR_INVALID_REQUEST."

    Claim: elected_deferral_pct=150 -> ERR_INVALID_REQUEST.
    """
    plan, participant = setup_basic_active_participant()
    res = api.update_deferral(
        plan["id"], participant["id"],
        update_deferral_payload(elected_deferral_pct=150.0),
        payroll_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )


def test_deferral_update_by_owning_participant_succeeds(api):
    """PRD §3.2: "Either the participant themselves or a
    PayrollProcessor may update elected_deferral_pct".

    Claim: PATCH deferral with Participant headers minted from the
    actual participant.id -> 200; new value persisted.

    This test verifies that ownership-gated PATCH succeeds when
    X-User-ID equals the Participant.id (PRD §2.1 entity_backed:Participant).
    """
    plan, participant = setup_basic_active_participant()
    headers = make_participant_headers(participant["id"])
    res = api.update_deferral(
        plan["id"], participant["id"],
        update_deferral_payload(elected_deferral_pct=7.5),
        headers,
    )
    updated = validate_success(res, 200)
    # Two decimal places, so float compare with tolerance.
    assert updated["elected_deferral_pct"] == pytest.approx(7.5, abs=0.001)


# ===========================================================================
# Termination — PRD §3.2
# ===========================================================================
def test_terminate_active_participant_succeeds(api, admin_headers):
    """PRD §3.2: "Termination of a participant is performed by a
    PlanAdministrator and is permitted from either ACTIVE or
    SUSPENDED; both paths transition the participant to the terminal
    TERMINATED state."

    Claim: terminate an ACTIVE participant -> status == 'TERMINATED'.
    """
    plan, participant = setup_basic_active_participant()
    res = api.terminate_participant(
        plan["id"], participant["id"], None, admin_headers,
    )
    terminated = validate_success(res, 200)
    assert terminated["status"] == "TERMINATED"


def test_terminate_blocked_by_active_loan(api, admin_headers):
    """PRD §3.2: "The precondition for either path is the same: the
    participant must have no Loan in ACTIVE status, otherwise the
    request is rejected with ERR_PARTICIPANT_NOT_IN_VALID_STATE."

    Claim: terminate with an outstanding ACTIVE loan ->
    ERR_PARTICIPANT_NOT_IN_VALID_STATE.

    # difficulty: cross_entity_state_dependency/participant_terminate_blocked_by_active_loan
    """
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

    res = api.terminate_participant(
        plan["id"], participant["id"], None, admin_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_PARTICIPANT_NOT_IN_VALID_STATE.value,
        expected_status=409,
    )
    # Participant must remain ACTIVE.
    p = validate_success(
        api.get_participant(plan["id"], participant["id"], admin_headers),
        200,
    )
    assert p["status"] == "ACTIVE"


def test_terminate_blocked_by_active_loan_alternate_setup(api, admin_headers):
    """PRD §3.2: same rule, exercised via a slightly different setup
    so the difficulty instance has TWO covering tests as required.

    # difficulty: cross_entity_state_dependency/participant_terminate_blocked_by_active_loan
    """
    plan, participant = setup_participant_with_balance(
        target_balance_cents=4_000_000,
        cliff_years=1,
        starting_clock="2026-02-01",
        hire_date="2020-06-15",
    )
    loan = request_and_approve_loan(
        plan["id"], participant["id"],
        requested_amount_cents=300_000, term_months=20,
    )
    assert loan["status"] == "ACTIVE"
    res = api.terminate_participant(
        plan["id"], participant["id"], None, admin_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_PARTICIPANT_NOT_IN_VALID_STATE.value,
        expected_status=409,
    )
