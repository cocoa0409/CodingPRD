"""Reconciliation-statement tests: drift dual-variant (write-off subtracts from expected vs
manual-recoup adds to actual), and consistency of clamped principal in the approve response.

Queue A (Difficulty): dual_variant_calc/reconciliation_writeoff_vs_manual_recoup_on_statement,
combinatorial_formula immediate-consistency surface.
Queue B (Corner): consistency_model.immediate_visibility_of_clamped_principal_in_approve_response.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    setup_base_scenario,
    setup_defaulted_with_draft_statement_319,
    post_shifts_for_gross_80000,
    request_advance,
)

OFFICER = TEST_USERS["payroll_officer_headers"]
SIGNER = TEST_USERS["compliance_officer_headers"]


# ===========================================================================
# Queue A — dual_variant_calc / reconciliation_writeoff_vs_manual_recoup_on_statement
# ===========================================================================
def test_statement_drift_discrepancy_before_writeoff(api):
    """PRD §3.11: "Its `drift_cents` is `expected_recoup_cents` minus `actual_recouped_cents`
    minus `written_off_cents`; the conservation invariant requires this to be 0 for clean books.
    The `outcome` is `CLEAN` when `drift_cents` is 0 and `DISCREPANCY` otherwise."

    A period run to payday with one INSTANT advance whose 319 fee remainder could not be recouped
    leaves drift 319 (outcome DISCREPANCY) before any resolution.

    Design: Difficulty/dual_variant_calc/reconciliation_writeoff_vs_manual_recoup_on_statement
    """
    employer, period, worker, adv, stmt = setup_defaulted_with_draft_statement_319()
    assert stmt["drift_cents"] == 319, f"drift must be 319 before write-off; got {stmt['drift_cents']}"
    assert stmt["outcome"] == "DISCREPANCY", f"outcome must be DISCREPANCY; got {stmt['outcome']}"


def test_writeoff_clears_drift_by_subtracting_from_expected(api):
    """PRD §3.11: "Its `written_off_cents` is the sum, over this period's advances that reached
    `WRITTEN_OFF`, of the outstanding amount captured at write-off."
    PRD §3.11: "a write-off subtracts from expected (it counts as resolved), so writing off a
    stuck balance can move an `outcome` from `DISCREPANCY` to `CLEAN` even though no cash was
    recovered — distinct from a manual recovery, which instead increases actual recouped."

    Writing off the 319 sets written_off_cents=319, driving drift to 0 and outcome to CLEAN —
    resolution via the expected column, not via actual_recouped.

    Design: Difficulty/dual_variant_calc/reconciliation_writeoff_vs_manual_recoup_on_statement
    """
    employer, period, worker, adv, stmt = setup_defaulted_with_draft_statement_319()
    get_success_data(api.write_off_advance(adv["id"], SIGNER))
    after = validate_success(api.create_reconciliation_statement({"pay_period_id": period["id"]}, SIGNER))

    assert after["written_off_cents"] == 319, f"written_off_cents must be 319; got {after['written_off_cents']}"
    assert after["drift_cents"] == 0, f"drift must clear to 0 after write-off; got {after['drift_cents']}"
    assert after["outcome"] == "CLEAN", f"outcome must be CLEAN after write-off; got {after['outcome']}"


# ===========================================================================
# Queue B — consistency_model / immediate_visibility_of_clamped_principal_in_approve_response
# ===========================================================================
def test_approve_response_immediately_reflects_clamped_principal(api):
    """PRD §3.5: "On a successful approval the system computes the approved `principal_cents` via
    the clamp described in Section 3.6, then computes `expedite_fee_cents`, `total_fee_cents`, and
    `recoup_target_cents` via the fee logic in Section 3.7, and sets `disbursed_amount_cents`
    equal to `principal_cents` (fees are recouped on top of the payout, never deducted from the
    worker's cash)."

    Requested 45000, available 40000: the approve response itself carries the clamped
    principal_cents 40000 and disbursed_amount_cents 40000 (immediate consistency).

    Design: Corner/consistency_model/immediate_visibility_of_clamped_principal_in_approve_response
    """
    employer, _p, _f, period, worker = setup_base_scenario()
    post_shifts_for_gross_80000(period["id"], worker["id"])
    adv = request_advance(worker["id"], period["id"], 45000, disbursement_speed="STANDARD")

    approved = validate_success(api.approve_advance(adv["id"], OFFICER))
    assert approved["principal_cents"] == 40000, (
        f"approve response must show clamped principal 40000; got {approved['principal_cents']}"
    )
    assert approved["disbursed_amount_cents"] == 40000, (
        f"disbursed_amount must equal principal 40000; got {approved['disbursed_amount_cents']}"
    )
