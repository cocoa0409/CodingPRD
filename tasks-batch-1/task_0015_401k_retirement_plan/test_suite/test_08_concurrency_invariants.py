"""Optimistic concurrency control, conservation invariants under compensating
actions, cascade atomicity on failure, and immediate-consistency reads.

Difficulty queue A — rule 9 (compensating_invariant).
Corner queue B — Section: errors (err_stale_version_triggerable_via_terminate),
Section: cross_cutting_complexity_layers (cascade_partial_failure_does_not_partially_apply),
Section: consistency_model (immediate_visibility_of_balance_changes_in_close_response).
"""
from test_helpers import (
    api_client,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    set_clock,
    create_and_activate_plan,
    create_and_enroll_participant,
    create_open_contribution_period,
    close_contribution_period,
    create_requested_loan,
    disburse_loan,
    create_pending_participant,
    setup_active_plan_with_enrolled_participant,
    setup_with_disbursed_loan,
    terminate_plan_payload,
    repay_loan_payload,
    create_plan_payload,
    create_loan_payload,
    get_participant,
    get_plan,
    get_loan,
    get_contribution_period,
    read_plan_version,
)

_ADMIN = TEST_USERS["plan_admin_headers"]


# ─── Difficulty/compensating_invariant ──────────────────────────────────────

def test_contribution_close_then_reverse_restores_employee_balance(api):
    """PRD §2.6: "A conservation invariant binds contribution periods to participant
    balances at all times: the participant's `employee_balance_cents` equals the
    sum of `employee_contribution_cents` across that participant's contribution
    periods whose status is `CLOSED`. Reversing a closed period (transition
    `CLOSED → REVERSED`) is a compensating action that subtracts the period's
    employee and employer contributions back out of the participant's balances
    and recomputes the vested employer balance; the invariant therefore holds
    before, after, and through the close-reverse pair."

    Design: Difficulty/compensating_invariant/contribution_close_then_reverse_preserves_employee_balance
    """
    _plan, participant = setup_active_plan_with_enrolled_participant(
        clock_iso="2026-06-15T00:00:00Z",
        plan_overrides={"name": "Inv1", "match_formula": "TIERED",
                        "vesting_schedule": "GRADED_6"},
        participant_overrides={"full_name": "N",
                               "hire_date": "2024-06-15T00:00:00Z",
                               "deferral_rate_bps": 400},
    )
    p0 = get_participant(participant["id"])
    assert p0["employee_balance_cents"] == 0
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=500_000)
    close_contribution_period(cp["id"])
    p_mid = get_participant(participant["id"])
    assert p_mid["employee_balance_cents"] == 20_000
    validate_success(api.reverse_contribution_period(cp["id"], _ADMIN))
    p_final = get_participant(participant["id"])
    assert p_final["employee_balance_cents"] == 0


def test_contribution_close_then_reverse_restores_employer_and_vested(api):
    """PRD §3.3: "The reversal is a compensating action: the participant's
    `employee_balance_cents` is reduced by that period's
    `employee_contribution_cents`, the participant's `employer_balance_cents` is
    reduced by that period's `employer_match_cents`, the participant's
    `vested_employer_balance_cents` is recomputed, and the period itself moves to
    `REVERSED` with a version bump."

    Design: Difficulty/compensating_invariant/contribution_close_then_reverse_preserves_employee_balance
    """
    _plan, participant = setup_active_plan_with_enrolled_participant(
        clock_iso="2026-06-15T00:00:00Z",
        plan_overrides={"name": "Inv1b", "match_formula": "TIERED",
                        "vesting_schedule": "GRADED_6"},
        participant_overrides={"full_name": "N2",
                               "hire_date": "2024-06-15T00:00:00Z",
                               "deferral_rate_bps": 400},
    )
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=500_000)
    close_contribution_period(cp["id"])
    reversed_cp = validate_success(api.reverse_contribution_period(cp["id"], _ADMIN))
    p = get_participant(participant["id"])
    assert p["employer_balance_cents"] == 0
    assert p["vested_employer_balance_cents"] == 0
    assert reversed_cp["status"] == "REVERSED"


def test_loan_disburse_then_repay_returns_outstanding_loan_principal_to_zero(api):
    """PRD §3.4: "A repayment — transitioning `DISBURSED → REPAID` — accepts a
    body field `amount_cents` that must be at least the loan's current
    `outstanding_principal_cents`; the participant or the plan administrator
    submits the payoff. On success the loan's `outstanding_principal_cents` is
    zeroed, the participant's `outstanding_loan_principal_cents` is reduced by
    the prior outstanding (depth-2 reconciliation), and the loan moves to
    `REPAID` with a version bump."

    Design: Difficulty/compensating_invariant/loan_disburse_then_repay_preserves_outstanding_loan_principal
    """
    _plan, participant, loan = setup_with_disbursed_loan(
        plan_overrides={"name": "Inv2", "match_formula": "TIERED",
                        "vesting_schedule": "GRADED_6"},
        gross_compensation_cents=10_000_000,
        loan_principal_cents=10_000,
    )
    mid = get_participant(participant["id"])
    assert mid["outstanding_loan_principal_cents"] == 10_000
    validate_success(api.repay_loan(loan["id"], repay_loan_payload(10_000), _ADMIN))
    final_p = get_participant(participant["id"])
    final_loan = get_loan(loan["id"])
    assert final_p["outstanding_loan_principal_cents"] == 0
    assert final_loan["outstanding_principal_cents"] == 0
    assert final_loan["status"] == "REPAID"


def test_loan_repay_transitions_loan_to_repaid(api):
    """PRD §3.4: "On success the loan's `outstanding_principal_cents` is zeroed, the participant's `outstanding_loan_principal_cents` is reduced by the prior outstanding (depth-2 reconciliation), and the loan moves to `REPAID` with a version bump."

    Design: Difficulty/compensating_invariant/loan_disburse_then_repay_preserves_outstanding_loan_principal
    """
    _plan, _participant, loan = setup_with_disbursed_loan(
        plan_overrides={"name": "Inv2b", "match_formula": "TIERED",
                        "vesting_schedule": "GRADED_6"},
        gross_compensation_cents=10_000_000,
        loan_principal_cents=10_000,
    )
    v_disbursed = loan["version"]
    repaid = validate_success(api.repay_loan(loan["id"], repay_loan_payload(10_000), _ADMIN))
    assert repaid["status"] == "REPAID"
    assert repaid["version"] == v_disbursed + 1


# ─── Corner/errors/err_stale_version_triggerable_via_terminate ──────────────

def test_plan_terminate_with_stale_expected_version_returns_412(api):
    """PRD §2.7: "Terminating a plan is the one administrative operation guarded
    by an optimistic-concurrency check on the parent `Plan` resource. The request
    body must include `expected_plan_version` — a non-optional integer field that
    carries the client's last observed `version` of the target plan. If
    `expected_plan_version` does not equal the plan's current `version`, the
    request is rejected with `ERR_STALE_VERSION` and an HTTP 412 status."

    Sequence: create -> activate (v=2) -> freeze (v=3) -> unfreeze (v=4) ->
    terminate with v=2 (stale). Server rejects.

    Design: Corner/errors/err_stale_version_triggerable_via_terminate
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = get_success_data(api.create_plan(
        create_plan_payload(name="OCC", match_formula="TIERED",
                            vesting_schedule="CLIFF_3"),
        _ADMIN,
    ))
    v_active = get_success_data(api.activate_plan(plan["id"], _ADMIN))["version"]
    get_success_data(api.freeze_plan(plan["id"], _ADMIN))
    get_success_data(api.unfreeze_plan(plan["id"], _ADMIN))
    # v_active is now stale.
    res = api.terminate_plan(plan["id"], terminate_plan_payload(v_active), _ADMIN)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    # Plan posture is unchanged.
    assert get_plan(plan["id"])["status"] == "ACTIVE"


# ─── Corner/cross_cutting/cascade_partial_failure_does_not_partially_apply ─

def test_plan_terminate_stale_version_leaves_participant_and_loan_intact(api):
    """PRD §2.7: "Terminating a plan is the one administrative operation guarded
    by an optimistic-concurrency check on the parent `Plan` resource... If
    `expected_plan_version` does not equal the plan's current `version`, the
    request is rejected with `ERR_STALE_VERSION` and an HTTP 412 status."

    On rejection no cascade is performed: the participant remains ENROLLED and
    the loan remains DISBURSED.

    Design: Corner/cross_cutting_complexity_layers/cascade_partial_failure_does_not_partially_apply
    """
    _plan, participant, loan = setup_with_disbursed_loan(
        plan_overrides={"name": "Atomic", "match_formula": "TIERED",
                        "vesting_schedule": "GRADED_6"},
        gross_compensation_cents=10_000_000,
        loan_principal_cents=20_000,
    )
    # Read pre-freeze version, then freeze+unfreeze to make it stale.
    v_pre = read_plan_version(_plan["id"])
    get_success_data(api.freeze_plan(_plan["id"], _ADMIN))
    get_success_data(api.unfreeze_plan(_plan["id"], _ADMIN))
    res = api.terminate_plan(_plan["id"], terminate_plan_payload(v_pre), _ADMIN)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    # No partial cascade: participant and loan still in original states.
    assert get_plan(_plan["id"])["status"] == "ACTIVE"
    assert get_participant(participant["id"])["enrollment_status"] == "ENROLLED"
    assert get_loan(loan["id"])["status"] == "DISBURSED"


# ─── Corner/consistency_model/immediate_visibility_of_balance_changes ──────

def test_close_contribution_period_visible_in_subsequent_participant_read(api):
    """PRD §2.6: "Similarly, closing a contribution period rolls forward the participant's `employee_balance_cents` and `employer_balance_cents` (depth 2), which in turn forces a recomputation of `vested_employer_balance_cents` (depth 3) — derived-field reconciliation is always strictly downstream of the field that triggered it."

    A GET /participants/{id} issued immediately after a successful close MUST
    return the post-cascade balances.

    Design: Corner/consistency_model/immediate_visibility_of_balance_changes_in_close_response
    """
    _plan, participant = setup_active_plan_with_enrolled_participant(
        clock_iso="2026-06-15T00:00:00Z",
        plan_overrides={"name": "Imm", "match_formula": "TIERED",
                        "vesting_schedule": "GRADED_6"},
        participant_overrides={"full_name": "Imm",
                               "hire_date": "2024-06-15T00:00:00Z",
                               "deferral_rate_bps": 400},
    )
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=500_000)
    validate_success(api.close_contribution_period(cp["id"], _ADMIN))
    p = get_participant(participant["id"])
    assert p["employee_balance_cents"] == 20_000
    assert p["employer_balance_cents"] == 17_500
