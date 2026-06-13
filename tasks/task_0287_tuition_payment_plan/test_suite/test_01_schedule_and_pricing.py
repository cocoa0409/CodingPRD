"""Installment scheduling, down-payment rounding, late-fee tiers, and refund
proration — the pricing-engine calculations of the tuition payment plan.

Difficulty queue: dual_variant_calc, combinatorial_formula (calculation halves),
resource_temporal_overlap (clamp), plus corner calculation/correct-result claims.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    fixtures,
    factories,
    TEST_USERS,
)

REGISTRAR = TEST_USERS["registrar_headers"]
BURSAR = TEST_USERS["bursar_headers"]


# ===========================================================================
# Difficulty: dual_variant_calc
# ===========================================================================
def test_refund_date_based_continuous_proration(api):
    """PRD 3.9: "Under the `DATE_BASED` variant, the retained charges are a
    continuous day-proportional fraction: `gross_charges_cents` multiplied by
    `days_elapsed` divided by `term_total_days`, rounded half up to whole cents."
    PRD 3.9: "The `refund_to_student_cents` is the greater of zero and
    `paid_principal_cents` minus the greater of zero and (`retained_charges_cents`
    minus `total_aid_cents`)"

    Identical inputs (gross 500000, aid 100000, paid_principal 240000,
    withdrawal at day 30 of a 122-day term) retain 122951 under DATE_BASED;
    refund_to_student 217049.

    Design: Difficulty/dual_variant_calc/refund_variant_diverges_date_vs_schedule
    """
    base = fixtures.setup_active_enrollment(
        charges_cents=500000, aid_cents=100000, refund_policy="DATE_BASED"
    )
    enr_id = base["enrollment"]["id"]
    # paid_principal 240000 = down 80000 + installments 1 and 2 (80000 each)
    fixtures.settle_down_payment(enr_id, 80000)
    installments = fixtures.list_installments(enr_id)
    fixtures.settle_installment(enr_id, installments[0]["id"], 80000)
    fixtures.settle_installment(enr_id, installments[1]["id"], 80000)

    fixtures.set_clock(base["institution"]["id"], "2026-09-30T00:00:00.000Z")
    fixtures.withdraw(enr_id, "2026-09-30T00:00:00.000Z")

    wd = fixtures.list_withdrawals(enr_id)[0]
    assert wd["variant_used"] == "DATE_BASED"
    assert wd["retained_charges_cents"] == 122951, wd
    assert wd["refund_to_student_cents"] == 217049, wd


def test_refund_schedule_based_bracket_proration(api):
    """PRD 3.9: "Under the `SCHEDULE_BASED` variant, the retained charges are a
    step function of `days_elapsed`: the institution retains 0 percent when
    `days_elapsed` is at most 7, 25 percent when `days_elapsed` is at least 8
    and at most 21, 50 percent when `days_elapsed` is at least 22 and at most
    42, and 100 percent when `days_elapsed` is greater than 42; the retained
    amount is `gross_charges_cents` multiplied by that bracket percentage,
    rounded half up to whole cents."

    Same inputs as the DATE_BASED case but SCHEDULE_BASED: day 30 falls in the
    22-42 bracket = 50%, so retained 250000 and refund 90000 — a different
    result for identical inputs.

    Design: Difficulty/dual_variant_calc/refund_variant_diverges_date_vs_schedule
    """
    base = fixtures.setup_active_enrollment(
        charges_cents=500000, aid_cents=100000, refund_policy="SCHEDULE_BASED"
    )
    enr_id = base["enrollment"]["id"]
    fixtures.settle_down_payment(enr_id, 80000)
    installments = fixtures.list_installments(enr_id)
    fixtures.settle_installment(enr_id, installments[0]["id"], 80000)
    fixtures.settle_installment(enr_id, installments[1]["id"], 80000)

    fixtures.set_clock(base["institution"]["id"], "2026-09-30T00:00:00.000Z")
    fixtures.withdraw(enr_id, "2026-09-30T00:00:00.000Z")

    wd = fixtures.list_withdrawals(enr_id)[0]
    assert wd["variant_used"] == "SCHEDULE_BASED"
    # retained = round_half_up(500000 * 0.50) = 250000
    assert wd["retained_charges_cents"] == 250000, wd
    # refund = max(0, 240000 - max(0, 250000 - 100000)) = max(0, 240000 - 150000) = 90000
    assert wd["refund_to_student_cents"] == 90000, wd


# ===========================================================================
# Difficulty: combinatorial_formula (installment schedule rounding order)
# ===========================================================================
def test_installment_schedule_round_down_payment_before_floor(api):
    """PRD 3.4: "The `down_payment_cents` is that net principal multiplied by
    `down_payment_pct`, rounded half up to whole cents — and this rounding
    happens *first*, before any flooring of the financed split"
    PRD 3.4: "The per-installment base amount is the financed principal divided
    by the installment count, rounded down to a whole number (floored)."

    Net 533300 * 0.15 -> round_half_up 79995 down payment, financed 453305 split
    5 ways = 90661 each (remainder 0).

    Design: Difficulty/combinatorial_formula/installment_schedule_round_then_floor_remainder
    """
    base = fixtures.setup_base(installment_count=5, down_payment_pct=0.15, plan_fee_cents=0)
    enr = fixtures.create_enrollment(
        base["student"]["id"], base["term"]["id"], base["template"]["id"]
    )
    fixtures.post_charge(enr["id"], 533300)
    enr = fixtures.activate(enr["id"])

    assert enr["down_payment_cents"] == 79995, enr
    assert enr["financed_principal_cents"] == 453305, enr
    installments = fixtures.list_installments(enr["id"])
    assert len(installments) == 5
    for inst in installments:
        assert inst["amount_cents"] == 90661, inst
    assert sum(i["amount_cents"] for i in installments) == 453305


def test_installment_schedule_remainder_onto_earliest(api):
    """PRD 3.4: "each installment's `amount_cents` is the base plus one
    additional cent for every installment whose sequence position is less than
    or equal to the remainder — that is, the leftover cents are distributed one
    each onto the *earliest* installments by sequence order."

    Net 400000 (gross 500000, aid 100000), down round_half_up(400000*0.20)=80000,
    financed 320000 over 4 = 80000 each, remainder 0 -> exact [80000 x4].

    Design: Difficulty/combinatorial_formula/installment_schedule_round_then_floor_remainder
    """
    base = fixtures.setup_pending_enrollment(charges_cents=500000, aid_cents=100000)
    enr = fixtures.activate(base["enrollment"]["id"])
    assert enr["down_payment_cents"] == 80000, enr
    assert enr["financed_principal_cents"] == 320000, enr
    installments = fixtures.list_installments(enr["id"])
    assert [i["amount_cents"] for i in installments] == [80000, 80000, 80000, 80000]


# ===========================================================================
# Difficulty: combinatorial_formula (late-fee tiered clamp)
# ===========================================================================
def test_late_fee_tier_two_percent_not_floor_not_cap(api):
    """PRD 3.7: "if `days_late` is at least 10 and less than 30 the rate is 4
    percent" ... "The percentage term is the overdue amount times the chosen
    rate, rounded half up to whole cents. The candidate fee is then the larger
    of a flat floor of 2,500 cents and that percentage term. That candidate is
    clamped into a band: at least the minimum of 2,500 cents and at most the
    maximum of 7,500 cents"

    Overdue 80000 at 12 days late -> 4% tier -> 3200, above the 2500 floor and
    below the 7500 cap.

    Design: Difficulty/combinatorial_formula/late_fee_tiered_clamp_three_inputs
    """
    base = fixtures.setup_active_enrollment(charges_cents=500000, aid_cents=100000)
    enr_id = base["enrollment"]["id"]
    fixtures.settle_down_payment(enr_id, 80000)
    fixtures.set_clock(base["institution"]["id"], "2026-10-07T00:00:00.000Z")
    fixtures.run_delinquency(enr_id)

    fees = fixtures.list_late_fees(enr_id)
    assert len(fees) == 1, fees
    assert fees[0]["amount_cents"] == 3200, fees[0]
    assert fees[0]["days_late"] == 12, fees[0]
    enr = fixtures.get_enrollment(enr_id)
    assert enr["late_fee_balance_cents"] == 3200, enr


# ===========================================================================
# Difficulty: resource_temporal_overlap (effective_date clamp)
# ===========================================================================
def test_withdrawal_effective_date_clamped_to_term_end(api):
    """PRD 3.9: "The effective date is clamped to the inclusive range from
    `term_start` to `term_end`, and `days_elapsed` is the whole number of days
    from `term_start` to that clamped date, computed as the floor of their
    difference in days plus one."

    effective_date past term_end (2027-01-15) saturates to term_end so
    days_elapsed == term_total_days (122); DATE_BASED retains the full
    gross_charges 500000.

    Design: Difficulty/resource_temporal_overlap/withdrawal_effective_date_clamped_to_term_span
    """
    base = fixtures.setup_active_enrollment(
        charges_cents=500000, aid_cents=100000, refund_policy="DATE_BASED"
    )
    enr_id = base["enrollment"]["id"]
    fixtures.settle_down_payment(enr_id, 80000)  # paid_principal 80000
    fixtures.withdraw(enr_id, "2027-01-15T00:00:00.000Z")

    wd = fixtures.list_withdrawals(enr_id)[0]
    assert wd["retained_charges_cents"] == 500000, wd
    # refund = max(0, 80000 - max(0, 500000 - 100000)) = max(0, 80000 - 400000) = 0
    assert wd["refund_to_student_cents"] == 0, wd


def test_withdrawal_clamp_net_owed_after_withdrawal(api):
    """PRD 3.9: "The `net_owed_after_withdrawal_cents` is the greater of zero and
    `retained_charges_cents` minus `total_aid_cents` minus `paid_principal_cents`
    — what the student still owes after retained charges are offset by aid and
    by what has already been paid."

    Same clamped withdrawal (effective_date past term_end -> retained 500000):
    net_owed = max(0, 500000 - 100000 - 80000) = 320000 — the settlement figure
    paired with the saturating clamp.

    Design: Difficulty/resource_temporal_overlap/withdrawal_effective_date_clamped_to_term_span
    """
    base = fixtures.setup_active_enrollment(
        charges_cents=500000, aid_cents=100000, refund_policy="DATE_BASED"
    )
    enr_id = base["enrollment"]["id"]
    fixtures.settle_down_payment(enr_id, 80000)  # paid_principal 80000
    fixtures.withdraw(enr_id, "2027-01-15T00:00:00.000Z")

    wd = fixtures.list_withdrawals(enr_id)[0]
    assert wd["retained_charges_cents"] == 500000, wd
    assert wd["net_owed_after_withdrawal_cents"] == 320000, wd


def test_late_fee_tier_three_six_percent(api):
    """PRD 3.7: "if `days_late` is at least 30 the rate is 6 percent. The
    percentage term is the overdue amount times the chosen rate, rounded half up
    to whole cents. The candidate fee is then the larger of a flat floor of
    2,500 cents and that percentage term. That candidate is clamped into a band:
    at least the minimum of 2,500 cents and at most the maximum of 7,500 cents"

    Overdue 80000 at 36 days late -> 6% tier -> round_half_up(4800)=4800, above
    the 2500 floor and below the 7500 cap — a different tier than the 12-day
    4% case.

    Design: Difficulty/combinatorial_formula/late_fee_tiered_clamp_three_inputs
    """
    base = fixtures.setup_active_enrollment(charges_cents=500000, aid_cents=100000)
    enr_id = base["enrollment"]["id"]
    fixtures.settle_down_payment(enr_id, 80000)
    # installment 1 due 2026-09-25; 2026-10-31 is 36 days late.
    fixtures.set_clock(base["institution"]["id"], "2026-10-31T00:00:00.000Z")
    fixtures.run_delinquency(enr_id)

    fees = [f for f in fixtures.list_late_fees(enr_id) if f["days_late"] == 36]
    assert fees, fixtures.list_late_fees(enr_id)
    assert fees[0]["amount_cents"] == 4800, fees[0]


# ===========================================================================
# Corner: calculations / down payment + plan fee snapshot
# ===========================================================================
def test_activation_snapshots_down_payment_and_plan_fee(api):
    """PRD 3.4: "It snapshots `installment_count`, `down_payment_pct`, and
    `plan_fee_cents` from the plan template onto the enrollment."
    PRD 3.4: "The `down_payment_cents` is that net principal multiplied by
    `down_payment_pct`, rounded half up to whole cents"

    Net 400000 on 4PAY -> down_payment_cents 80000, plan_fee_cents snapshot 4500,
    financed_principal 320000.

    Design: Corner/calculations/down_payment_collected_with_plan_fee_at_activation
    """
    base = fixtures.setup_pending_enrollment(charges_cents=500000, aid_cents=100000)
    enr = fixtures.activate(base["enrollment"]["id"])
    assert enr["down_payment_cents"] == 80000, enr
    assert enr["plan_fee_cents"] == 4500, enr
    assert enr["financed_principal_cents"] == 320000, enr


# ===========================================================================
# Corner: calculations / aid application re-spread reduces latest first
# ===========================================================================
def test_aid_application_reduces_latest_installment_first(api):
    """PRD 3.5: "*applying* aid is a negative delta to the financed principal
    (it reduces owed, so the credit comes off the latest installments
    backward)" ... "the system takes the magnitude of the credit and walks the
    scheduled installments from the *latest* sequence index backward, reducing
    each installment's `amount_cents` by as much of the remaining credit as
    that installment holds"

    Applying 50000 aid to ACTIVE [80000 x4] reduces installment 4 to 30000,
    installments 1-3 unchanged, scheduled_balance 270000.

    Design: Corner/calculations/aid_apply_reduces_latest_installment_first
    """
    base = fixtures.setup_active_enrollment(charges_cents=400000, aid_cents=0)
    enr_id = base["enrollment"]["id"]
    assert [i["amount_cents"] for i in base["installments"]] == [80000, 80000, 80000, 80000]

    fixtures.apply_aid(enr_id, 50000, source="SCHOLARSHIP")
    installments = fixtures.list_installments(enr_id)
    assert installments[3]["amount_cents"] == 30000, installments
    assert [i["amount_cents"] for i in installments[:3]] == [80000, 80000, 80000]
    enr = fixtures.get_enrollment(enr_id)
    assert enr["scheduled_balance_cents"] == 270000, enr


# ===========================================================================
# Corner: calculations / positive charge delta spreads over scheduled only
# ===========================================================================
def test_charge_delta_spreads_over_scheduled_installments_only(api):
    """PRD 3.5: "The installments eligible to absorb the delta are exactly
    those still in `SCHEDULED` status, taken in ascending `sequence_index`
    order; installments already `PAID` or already `OVERDUE` are frozen at their
    current `amount_cents` and never touched." ... "it then adds the base to
    every scheduled installment and one extra cent to each of the earliest
    installments up to the remainder"

    After installment 1 is PAID, posting a 60000 charge spreads only over the 3
    remaining SCHEDULED installments (+20000 each); installment 1 stays 80000.

    Design: Corner/calculations/charge_delta_spreads_over_scheduled_only
    """
    base = fixtures.setup_active_enrollment(charges_cents=500000, aid_cents=100000)
    enr_id = base["enrollment"]["id"]
    fixtures.settle_down_payment(enr_id, 80000)
    installments = fixtures.list_installments(enr_id)
    fixtures.settle_installment(enr_id, installments[0]["id"], 80000)

    fixtures.post_charge(enr_id, 60000, kind="FEE")
    installments = fixtures.list_installments(enr_id)
    assert installments[0]["amount_cents"] == 80000, installments[0]
    assert installments[0]["status"] == "PAID", installments[0]
    assert [i["amount_cents"] for i in installments[1:]] == [100000, 100000, 100000]
    enr = fixtures.get_enrollment(enr_id)
    assert enr["scheduled_balance_cents"] == 300000, enr


# ===========================================================================
# Corner: consistency_model / charge recalc visible immediately
# ===========================================================================
def test_charge_recalc_visible_in_immediate_read(api):
    """PRD 3.5: "Posting a new charge against an active enrollment raises the
    net principal, a positive delta" ... "it then adds the base to every
    scheduled installment and one extra cent to each of the earliest
    installments up to the remainder"
    PRD 2.8: "when a child resource changes in a way that affects a parent's
    derived totals or eligibility, the parent is recomputed in the same
    operation"

    Posting a 40000 FEE charge to ACTIVE [80000 x4] yields scheduled_balance
    360000 (+10000 x4) in the immediate GET, gross 540000.

    Design: Corner/consistency_model/charge_recalc_visible_immediately
    """
    base = fixtures.setup_active_enrollment(charges_cents=500000, aid_cents=100000)
    enr_id = base["enrollment"]["id"]
    fixtures.post_charge(enr_id, 40000, kind="FEE")
    enr = fixtures.get_enrollment(enr_id)
    assert enr["scheduled_balance_cents"] == 360000, enr
    assert enr["gross_charges_cents"] == 540000, enr
