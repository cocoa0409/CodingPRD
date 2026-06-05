"""Late-fee assessment timing, the path to default, the charge-off cascade,
committed-capital conservation, and recovery limits.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_repayment_loan, setup_single_investor_repayment_loan,
    setup_charged_off_loan,
    drive_to_defaulted, drive_to_charged_off,
    assess_late_fee, set_clock, get_loan, post_repayment,
    ADMIN,
)


# =====================================================================
# Rule 3b — non-linear state machine: REPAYMENT -> PAID_OFF vs DEFAULTED/CHARGED_OFF
# =====================================================================

def test_loan_branch_reaches_paid_off(api):
    """PRD §3.6: "When a scheduled repayment fully retires the loan — that is, after
    this payment's allocation the loan's `outstanding_principal_cents` is 0 and its
    `late_fee_outstanding_cents` is 0 — the loan transitions from `REPAYMENT` to
    `PAID_OFF`"

    Design: Difficulty/non_linear_state_machine/loan_branch_repayment_to_paidoff_vs_defaulted_chargedoff
    """
    ctx = setup_repayment_loan([800_000, 400_000])
    post_repayment(ctx["loan"]["id"], 1_205_990, kind="SCHEDULED")
    loan = get_loan(ctx["loan"]["id"])
    assert loan["status"] == "PAID_OFF"
    assert loan["outstanding_principal_cents"] == 0


def test_loan_branch_reaches_defaulted_then_charged_off(api):
    """PRD §3.7: "additionally sets the loan's `status` to `DEFAULTED` in the same
    request."
    PRD §3.7: "A `PlatformAdmin` charges off a defaulted loan, advancing it from
    `DEFAULTED` to `CHARGED_OFF`"

    Design: Difficulty/non_linear_state_machine/loan_branch_repayment_to_paidoff_vs_defaulted_chargedoff
    """
    ctx = setup_repayment_loan([800_000, 400_000])
    defaulted = drive_to_defaulted(ctx["loan"]["id"])
    assert defaulted["status"] == "DEFAULTED"
    validate_success(api.charge_off_loan(ctx["loan"]["id"], ADMIN), 200)
    assert get_loan(ctx["loan"]["id"])["status"] == "CHARGED_OFF"


# =====================================================================
# Rule 4a — depth-3 cascade: charge-off -> investment write-off -> investor write-down
# =====================================================================

def test_chargeoff_cascade_writes_off_investments_and_investor_capital(api):
    """PRD §3.7: "for each `COMMITTED` investment on the loan, the investment's
    `status` is set to `WRITTEN_OFF`, its `charged_off_basis_cents` is snapshotted
    from its current `outstanding_principal_cents` ... and only then is its
    `outstanding_principal_cents` zeroed."
    PRD §3.7: "the owning investor's `committed_capital_cents` is decremented by that
    investment's `amount_cents`, and the investor's `capital_base_cents` is
    decremented by that investment's outstanding principal at charge-off"

    Design: Difficulty/transitive_cascade/chargeoff_cascade_loan_investment_investor_depth3
    """
    ctx = setup_repayment_loan([800_000, 400_000])
    drive_to_charged_off(ctx["loan"]["id"])
    invx = validate_success(api.get_investment(ctx["investments"][0]["id"], ADMIN), 200)
    invy = validate_success(api.get_investment(ctx["investments"][1]["id"], ADMIN), 200)
    assert invx["status"] == "WRITTEN_OFF"
    assert invx["outstanding_principal_cents"] == 0
    assert invx["charged_off_basis_cents"] == 800_000
    investor_x = validate_success(api.get_investor(ctx["investors"][0]["id"], ADMIN), 200)
    investor_y = validate_success(api.get_investor(ctx["investors"][1]["id"], ADMIN), 200)
    # capital_base 5,000,000 each; charge-off subtracts the realised loss (outstanding).
    assert investor_x["committed_capital_cents"] == 0
    assert investor_x["capital_base_cents"] == 4_200_000
    assert investor_y["committed_capital_cents"] == 0
    assert investor_y["capital_base_cents"] == 4_600_000


def test_chargeoff_loan_status_and_basis_preserved(api):
    """PRD §3.7: "the loan's `status` becomes `CHARGED_OFF`, while its
    `outstanding_principal_cents` is deliberately preserved as the charged-off basis
    from which later recovery is distributed."

    Design: Difficulty/transitive_cascade/chargeoff_cascade_loan_investment_investor_depth3
    """
    ctx = setup_repayment_loan([800_000, 400_000])
    drive_to_charged_off(ctx["loan"]["id"])
    loan = get_loan(ctx["loan"]["id"])
    assert loan["status"] == "CHARGED_OFF"
    assert loan["outstanding_principal_cents"] == 1_200_000, "basis preserved for recovery"


# =====================================================================
# Rule 8a — temporal: late-fee window must be STRICTLY past the due instant
# =====================================================================

def test_late_fee_at_exact_due_instant_rejected(api):
    """PRD §3.7: "the target period's due date — the `funded_at` instant advanced by
    that many months — must be strictly before the current clock time. If the target
    period is not yet due ... the assessment is rejected with
    `ERR_LATE_FEE_NOT_DUE`."

    Design: Difficulty/resource_temporal_overlap/late_fee_period_window_strictly_past_due_date
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_single_investor_repayment_loan()  # funded_at 2026-06-01, period 1 due 2026-07-01
    set_clock("2026-07-01T00:00:00.000Z")  # exactly the due instant -> not strictly before
    resp = api.assess_late_fee(ctx["loan"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_LATE_FEE_NOT_DUE.value, 409)
    loan = get_loan(ctx["loan"]["id"])
    assert loan["missed_payment_count"] == 0, "no assessment at the exact due instant"


def test_late_fee_one_day_past_due_succeeds(api):
    """PRD §3.7: "A successful assessment raises the loan's
    `late_fee_outstanding_cents` by that amount, sets `last_assessed_period_index`
    to the target period, and increments `missed_payment_count` by one."

    Design: Difficulty/resource_temporal_overlap/late_fee_period_window_strictly_past_due_date
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_single_investor_repayment_loan()
    set_clock("2026-07-02T00:00:00.000Z")  # strictly past period 1 due
    data = validate_success(api.assess_late_fee(ctx["loan"]["id"], ADMIN), 200)
    assert data["missed_payment_count"] == 1
    assert data["last_assessed_period_index"] == 1


# =====================================================================
# Rule 9b — compensating invariant: total committed-capital write-down == committed_cents
# =====================================================================

def test_committed_capital_writeoff_equals_loan_committed_cents(api):
    """PRD §2.8: "An investor's `committed_capital_cents` is the sum of the
    `amount_cents` across all of that investor's `COMMITTED` investments on all
    loans"
    PRD §3.7: "the owning investor's `committed_capital_cents` is decremented by that
    investment's `amount_cents`"

    Design: Difficulty/compensating_invariant/committed_capital_conservation_writeoff_equals_committed_on_chargeoff
    """
    ctx = setup_repayment_loan([800_000, 400_000])
    loan_before = get_loan(ctx["loan"]["id"])
    assert loan_before["committed_cents"] == 1_200_000
    drive_to_charged_off(ctx["loan"]["id"])
    investor_x = validate_success(api.get_investor(ctx["investors"][0]["id"], ADMIN), 200)
    investor_y = validate_success(api.get_investor(ctx["investors"][1]["id"], ADMIN), 200)
    # Each had only this one investment, so committed_capital was its amount; now 0.
    assert investor_x["committed_capital_cents"] == 0
    assert investor_y["committed_capital_cents"] == 0
    total_decrement = 800_000 + 400_000
    assert total_decrement == loan_before["committed_cents"], \
        "total committed-capital write-down equals the loan's funded principal"


def test_loan_committed_cents_unchanged_by_chargeoff(api):
    """PRD §2.8: "A loan's `committed_cents` is the running sum of the `amount_cents`
    of every `COMMITTED` investment on that loan and is reconciled on every
    investment commit."

    Design: Difficulty/compensating_invariant/committed_capital_conservation_writeoff_equals_committed_on_chargeoff
    """
    ctx = setup_repayment_loan([800_000, 400_000])
    drive_to_charged_off(ctx["loan"]["id"])
    loan = get_loan(ctx["loan"]["id"])
    assert loan["committed_cents"] == 1_200_000, "committed_cents records funded principal"


# =====================================================================
# Corner — calculations: late-fee floor via max
# =====================================================================

def test_late_fee_amount_five_percent_exceeds_floor(api):
    """PRD §3.7: "The late fee itself is the greater of a floor of 2500 cents and
    five percent (`0.05`) of the loan's level scheduled payment
    (`level_payment_cents`), with the percentage result rounded to whole cents using
    round-half-up"

    Design: Corner/calculations/late_fee_floor_applies_via_max
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_single_investor_repayment_loan()  # level payment 103274
    set_clock("2026-07-02T00:00:00.000Z")
    data = validate_success(api.assess_late_fee(ctx["loan"]["id"], ADMIN), 200)
    # 5% of 103274 = 5163.7 -> 5164 > floor 2500.
    assert data["late_fee_outstanding_cents"] == 5164
    assert data["missed_payment_count"] == 1
    assert data["last_assessed_period_index"] == 1


# =====================================================================
# Corner — validations: idempotent assess per period
# =====================================================================

def test_assess_late_fee_repeat_for_future_period_rejected(api):
    """PRD §3.7: "Because each call advances `last_assessed_period_index` by exactly
    one, re-assessing an already-assessed period is naturally blocked by the
    unpaid-period condition."

    Design: Corner/validations/assess_late_fee_idempotent_per_period_rejects_repeat
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_single_investor_repayment_loan()
    set_clock("2026-07-02T00:00:00.000Z")  # past period 1 due, before period 2 due
    validate_success(api.assess_late_fee(ctx["loan"]["id"], ADMIN), 200)  # period 1
    # Second call targets period 2 whose due date (2026-08-01) is still future.
    resp = api.assess_late_fee(ctx["loan"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_LATE_FEE_NOT_DUE.value, 409)
    assert get_loan(ctx["loan"]["id"])["missed_payment_count"] == 1


# =====================================================================
# Corner — validations: recovery exceeds basis
# =====================================================================

def test_recovery_exceeds_basis_rejected(api):
    """PRD §3.7: "its `amount_cents` may not exceed the loan's preserved charged-off
    `outstanding_principal_cents` basis; an over-recovery is rejected with
    `ERR_RECOVERY_EXCEEDS_BASIS`."

    Design: Corner/validations/recovery_exceeds_basis_rejected
    """
    ctx = setup_charged_off_loan([1_200_000])  # basis 1,200,000
    resp = api.create_repayment(
        ctx["loan"]["id"],
        {"loan_id": ctx["loan"]["id"], "amount_cents": 1_300_000, "kind": "RECOVERY"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_RECOVERY_EXCEEDS_BASIS.value, 422)


# =====================================================================
# Corner — cross-cutting: third missed payment triggers default
# =====================================================================

def test_third_missed_payment_triggers_default(api):
    """PRD §3.7: "But when an assessment is made on a loan whose
    `missed_payment_count` is exactly 2 beforehand, that assessment carries out the
    same fee accrual ... and additionally sets the loan's `status` to `DEFAULTED` in
    the same request."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_third_missed_payment_triggers_default
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_single_investor_repayment_loan()
    set_clock("2026-09-02T00:00:00.000Z")  # past periods 1-3 due dates
    a1 = validate_success(api.assess_late_fee(ctx["loan"]["id"], ADMIN), 200)
    assert a1["status"] == "REPAYMENT" and a1["missed_payment_count"] == 1
    a2 = validate_success(api.assess_late_fee(ctx["loan"]["id"], ADMIN), 200)
    assert a2["status"] == "REPAYMENT" and a2["missed_payment_count"] == 2
    a3 = validate_success(api.assess_late_fee(ctx["loan"]["id"], ADMIN), 200)
    assert a3["missed_payment_count"] == 3
    assert a3["status"] == "DEFAULTED"
    assert a3["late_fee_outstanding_cents"] == 15492  # 3 * 5164
