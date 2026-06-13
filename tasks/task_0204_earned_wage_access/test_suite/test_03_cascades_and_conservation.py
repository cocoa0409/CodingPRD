"""Cascade and conservation tests: payday default->hold->recon->freeze (depth 4),
batch-post recoup->recouping->settled->funding-credit (depth 3), funding-pool conservation,
exposure conservation across default/write-off.

Queue A (Difficulty): transitive_cascade, compensating_invariant.
Queue B (Corner): cross_cutting_complexity_layers.derived_outstanding_principal_reconciles_after_disburse.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    setup_base_scenario,
    setup_disbursed_instant_advance_6000,
    setup_settled_full_recoup_advance_12000,
    setup_defaulted_advance_319,
    post_shifts_for_gross_80000,
    post_shift_6h_gross_12000,
    request_approve_disburse_advance,
    lock_period,
    open_batch,
    post_batch,
    lock_and_post_batch,
    run_payday,
)

OFFICER = TEST_USERS["payroll_officer_headers"]
SIGNER = TEST_USERS["compliance_officer_headers"]


# ===========================================================================
# Queue A — transitive_cascade / run_payday_default_to_hold_to_recon_to_freeze_depth4
# ===========================================================================
def test_run_payday_defaults_advance_and_holds_worker(api):
    """PRD §3.8: "every advance in the period still in `RECOUPING` with `principal_outstanding_cents`
    greater than 0 is defaulted, moving `RECOUPING → DEFAULTED`".
    PRD §3.8: "each newly defaulted advance sets its worker's `advance_eligibility` to `ON_HOLD`."

    INSTANT advance (rt 6319), worker gross 12000 => cap 6000, batch recoups only 6000 leaving
    319; run-payday defaults the advance (hop 1) which holds the worker (hop 2).

    Design: Difficulty/transitive_cascade/run_payday_default_to_hold_to_recon_to_freeze_depth4
    """
    employer, period, worker, adv = setup_disbursed_instant_advance_6000()
    lock_and_post_batch(period["id"])
    run_payday(period["id"])

    adv_after = validate_success(api.get_advance(adv["id"], OFFICER))
    worker_after = validate_success(api.get_worker(worker["id"], OFFICER))
    assert adv_after["status"] == "DEFAULTED", f"advance must default; got {adv_after['status']}"
    assert worker_after["advance_eligibility"] == "ON_HOLD", (
        f"defaulted advance must hold worker; got {worker_after['advance_eligibility']}"
    )


def test_run_payday_discrepancy_freezes_employer(api):
    """PRD §3.8: "the period's reconciliation statement is recomputed (creating a `DRAFT`
    statement if none exists) so its `drift_cents` reflects the new defaults. Fourth, if the
    recomputed statement's `outcome` is `DISCREPANCY`, the employer's `posture` is recomputed to
    `FROZEN`."

    The unrecouped 319 leaves drift 319 (DISCREPANCY, hop 3), which freezes the employer (hop 4).

    Design: Difficulty/transitive_cascade/run_payday_default_to_hold_to_recon_to_freeze_depth4
    """
    employer, period, worker, adv = setup_disbursed_instant_advance_6000()
    lock_and_post_batch(period["id"])
    run_payday(period["id"])

    emp_after = validate_success(api.get_employer(employer["id"], OFFICER))
    assert emp_after["posture"] == "FROZEN", (
        f"DISCREPANCY statement must freeze employer; got {emp_after['posture']}"
    )


# ===========================================================================
# Queue A — transitive_cascade / batch_post_recoup_to_recouping_to_settled_to_funding_credit_depth3
# ===========================================================================
def test_batch_post_settles_advance(api):
    """PRD §3.8: "On success it creates the `Repayment` rows produced by the waterfall, cascades
    each touched advance from `DISBURSED → RECOUPING`, further cascades any advance whose
    outstanding reaches 0 from `RECOUPING → SETTLED` (which credits the funding pool as described
    below)".

    STANDARD advance principal 12000 (rt 12000), worker gross 80000 => cap 40000 >= 12000, so the
    batch fully recoups: DISBURSED -> RECOUPING (hop 1) -> SETTLED (hop 2).

    Design: Difficulty/transitive_cascade/batch_post_recoup_to_recouping_to_settled_to_funding_credit_depth3
    """
    employer, period, worker, adv, batch = setup_settled_full_recoup_advance_12000()
    adv_after = validate_success(api.get_advance(adv["id"], OFFICER))
    assert adv_after["status"] == "SETTLED", f"advance must settle on full recoup; got {adv_after['status']}"


def test_batch_post_credits_funding_on_settle(api):
    """PRD §3.9: "On settlement the employer's `funding_balance_cents` is credited by the
    advance's `recoup_target_cents` — closing the conservation loop opened at disbursement".

    Funding starts 100000; disburse debits 12000; full-recoup settle credits 12000 back => 100000
    (hop 3, the funding credit caused by the settle).

    Design: Difficulty/transitive_cascade/batch_post_recoup_to_recouping_to_settled_to_funding_credit_depth3
    """
    employer, period, worker, adv, batch = setup_settled_full_recoup_advance_12000()
    emp_after = validate_success(api.get_employer(employer["id"], OFFICER))
    assert emp_after["funding_balance_cents"] == 100000, (
        f"settle must credit 12000 back to 100000; got {emp_after['funding_balance_cents']}"
    )


# ===========================================================================
# Queue A — compensating_invariant / funding_pool_conserved_across_disburse_and_settle
# ===========================================================================
def test_funding_conserved_after_disburse(api):
    """PRD §2.9: "The pool obeys a conservation invariant: it is debited by an advance's full
    recoup target (principal plus fee) at disbursement and credited back by that same recoup
    target when the advance settles, so that the pool plus the employer's outstanding exposure is
    conserved across the advance lifecycle."
    PRD §2.9: "The employer's `outstanding_principal_cents` is the running sum of
    `principal_outstanding_cents` across all of that employer's advances that are not in a
    terminal recovery state."

    After disburse of a 12000 STANDARD advance: funding 88000 + outstanding 12000 = 100000.

    Design: Difficulty/compensating_invariant/funding_pool_conserved_across_disburse_and_settle
    """
    employer, _p, _f, period, worker = setup_base_scenario()
    post_shifts_for_gross_80000(period["id"], worker["id"])
    request_approve_disburse_advance(worker["id"], period["id"], 12000, disbursement_speed="STANDARD")

    emp_mid = validate_success(api.get_employer(employer["id"], OFFICER))
    assert emp_mid["funding_balance_cents"] == 88000
    assert emp_mid["outstanding_principal_cents"] == 12000
    assert emp_mid["funding_balance_cents"] + emp_mid["outstanding_principal_cents"] == 100000


def test_funding_conserved_after_settle(api):
    """PRD §2.9: "it is debited by an advance's full recoup target (principal plus fee) at
    disbursement and credited back by that same recoup target when the advance settles, so that
    the pool plus the employer's outstanding exposure is conserved across the advance lifecycle."

    After full recoup + settle: funding 100000 + outstanding 0 = 100000 (conserved).

    Design: Difficulty/compensating_invariant/funding_pool_conserved_across_disburse_and_settle
    """
    employer, period, worker, adv, batch = setup_settled_full_recoup_advance_12000()
    emp_end = validate_success(api.get_employer(employer["id"], OFFICER))
    assert emp_end["funding_balance_cents"] == 100000
    assert emp_end["outstanding_principal_cents"] == 0
    assert emp_end["funding_balance_cents"] + emp_end["outstanding_principal_cents"] == 100000


# ===========================================================================
# Queue A — compensating_invariant / exposure_conserved_across_default_and_writeoff
# ===========================================================================
def test_exposure_in_outstanding_before_writeoff(api):
    """PRD §3.8: "any advance still in `DISBURSED` with outstanding above 0 at payday moves
    `DISBURSED → DEFAULTED`."

    The 319 fee remainder sits in principal_outstanding_cents after the advance defaults.

    Design: Difficulty/compensating_invariant/exposure_conserved_across_default_and_writeoff
    """
    employer, period, worker, adv = setup_defaulted_advance_319()
    adv_before = validate_success(api.get_advance(adv["id"], OFFICER))
    assert adv_before["principal_outstanding_cents"] == 319, (
        f"exposure 319 must sit in outstanding; got {adv_before['principal_outstanding_cents']}"
    )


def test_exposure_moves_to_written_off_after_writeoff(api):
    """PRD §3.9: "On success the written-off amount equals the current `principal_outstanding_cents`,
    which is then set to 0".
    PRD §3.11: "Its `written_off_cents` is the sum, over this period's advances that reached
    `WRITTEN_OFF`, of the outstanding amount captured at write-off."

    Write-off moves the 319 from outstanding to written_off — total exposure-ever stays 319.

    Design: Difficulty/compensating_invariant/exposure_conserved_across_default_and_writeoff
    """
    employer, period, worker, adv = setup_defaulted_advance_319()
    get_success_data(api.write_off_advance(adv["id"], SIGNER))
    stmt = validate_success(api.create_reconciliation_statement({"pay_period_id": period["id"]}, SIGNER))
    adv_after = validate_success(api.get_advance(adv["id"], OFFICER))

    assert adv_after["principal_outstanding_cents"] == 0, (
        f"outstanding must be 0 after write-off; got {adv_after['principal_outstanding_cents']}"
    )
    assert stmt["written_off_cents"] == 319, (
        f"written_off_cents must capture 319; got {stmt['written_off_cents']}"
    )


# ===========================================================================
# Queue B — cross_cutting / derived_outstanding_principal_reconciles_after_disburse
# ===========================================================================
def test_outstanding_principal_reconciles_after_disburse(api):
    """PRD §2.9: "The employer's `outstanding_principal_cents` is the running sum of
    `principal_outstanding_cents` across all of that employer's advances that are not in a
    terminal recovery state."
    PRD §3.8: "sets `principal_outstanding_cents` to `recoup_target_cents`, recomputes the
    worker's `lifetime_advanced_cents` and `period_advance_count` and the employer's
    `outstanding_principal_cents`".

    One disbursed STANDARD advance principal 12000 => employer outstanding 12000.

    Design: Corner/cross_cutting_complexity_layers/derived_outstanding_principal_reconciles_after_disburse
    """
    employer, _p, _f, period, worker = setup_base_scenario()
    post_shifts_for_gross_80000(period["id"], worker["id"])
    request_approve_disburse_advance(worker["id"], period["id"], 12000, disbursement_speed="STANDARD")

    emp = validate_success(api.get_employer(employer["id"], OFFICER))
    assert emp["outstanding_principal_cents"] == 12000, (
        f"outstanding must reconcile to 12000; got {emp['outstanding_principal_cents']}"
    )
