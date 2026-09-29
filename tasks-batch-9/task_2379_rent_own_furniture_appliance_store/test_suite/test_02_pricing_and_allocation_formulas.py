"""Formulas whose answer depends on where the rounding and the bases sit.

Three pinned orderings are exercised: the five allocation buckets a single payment
walks, the round-up-then-multiply that inflates the disclosed subtotal, and the
processing-fee base that is the rent subtotal rather than the grand total.
"""

from __future__ import annotations

from test_helpers import (
    DAY_12,
    M12_PROCESSING_FEE_CENTS,
    M12_RENEWAL_RATE_CENTS,
    M12_RENT_SUBTOTAL_CENTS,
    M12_TOTAL_OF_PAYMENTS_CENTS,
    W52_ADJUSTED_CASH_PRICE_CENTS,
    W52_COST_OF_RENTAL_CENTS,
    W52_MONTHLY_EQUIVALENT_CENTS,
    W52_PROCESSING_FEE_CENTS,
    W52_RENEWAL_RATE_CENTS,
    W52_RENT_SUBTOTAL_CENTS,
    W52_TOTAL_OF_PAYMENTS_CENTS,
    WASHER_CASH_PRICE_CENTS,
    Category,
    CollectionsStage,
    PayoffFormula,
    PaymentRowStatus,
    PaymentStatus,
    PossessionStatus,
    TermType,
    UnitStatus,
    WindowStatus,
    assert_cash_conserved,
    assert_fields,
    assert_paid_pct,
    assert_pricing,
    assert_signing_anchors_unset,
    build_tx_floor,
    deliver_on,
    sign_on,
)

TARGET_TOTAL_CENTS = 264000  # 120,000 cents of adjusted cash price at the weekly 2.20 markup
FEE_ON_THE_GRAND_TOTAL_CENTS = 61571  # what folding the fee into its own base would disclose


def _delinquent_with_carried_credit(world):
    """A sub-rate payment carried forward, then a day-close that assesses the arrears.

    The renter tenders 4,000 cents on the day of delivery — less than one 5,077 cent
    period — and then lets the first due date pass by four days.
    """
    scenario = deliver_on(sign_on(build_tx_floor(world)))
    first = world.pay(scenario.agreement_id, 4000)
    world.set_clock(DAY_12)
    world.day_close(scenario.store_id)
    return scenario, first


def test_a_sub_rate_payment_buys_no_period_and_earns_no_points(world):
    """Partial money is carried, never rounded up into a paid period.

    PRD: `periods_advanced` is the number of whole periods the pool covers at `renewal_rate_cents` each — the pool divided by the rate, rounded **down** — but never more periods than remain between `periods_paid` and `renewal_count`.

    Design: Difficulty/combinatorial_formula/allocation_waterfall_partial_credit_plus_two_arrears_buckets
    """
    scenario = deliver_on(sign_on(build_tx_floor(world)))

    payment = world.pay(scenario.agreement_id, 4000)
    assert_fields(
        payment,
        amount_cents=4000,
        allocation_late_fee_cents=0,
        allocation_reinstatement_fee_cents=0,
        partial_credit_before_cents=0,
        periods_advanced=0,
        allocation_rent_cents=0,
        allocation_partial_credit_cents=4000,
        allocation_customer_credit_cents=0,
        days_late=0,
        cured_delinquency=False,
        loyalty_points_awarded=0,
        status=PaymentRowStatus.POSTED,
    )

    agreement = scenario.read_agreement()
    assert_fields(
        agreement,
        periods_paid=0,
        rent_applied_cents=0,
        partial_credit_cents=4000,
        payment_status=PaymentStatus.CURRENT,
        current_period_due_at="2026-08-08T00:00:00Z",
    )
    assert_paid_pct(agreement, 0.0000)
    assert_cash_conserved(agreement, world.payments(scenario.agreement_id))
    assert world.ledger(customer_id=scenario.customer_id) == [], (
        "a payment that advanced no period earns nothing, so no ledger entry is appended"
    )


def test_one_payment_walks_the_late_fee_reinstatement_and_rent_buckets_in_order(world):
    """Arrears are taken first, then the carried credit joins the rent pool.

    PRD: **Bucket one** takes the smaller of the remaining money and `late_fee_balance_cents` into `allocation_late_fee_cents`.

    Design: Difficulty/combinatorial_formula/allocation_waterfall_partial_credit_plus_two_arrears_buckets
    """
    scenario, _first = _delinquent_with_carried_credit(world)

    payment = world.pay(scenario.agreement_id, 9000)
    assert_fields(
        payment,
        amount_cents=9000,
        allocation_late_fee_cents=508,
        allocation_reinstatement_fee_cents=500,
        partial_credit_before_cents=4000,
        periods_advanced=2,
        allocation_rent_cents=10154,
        allocation_partial_credit_cents=1838,
        allocation_customer_credit_cents=0,
        days_late=4,
        cured_delinquency=True,
        loyalty_points_awarded=101,
        status=PaymentRowStatus.POSTED,
    )
    assert (
        payment["allocation_late_fee_cents"]
        + payment["allocation_reinstatement_fee_cents"]
        + payment["allocation_rent_cents"]
        + payment["allocation_partial_credit_cents"]
        == payment["amount_cents"] + payment["partial_credit_before_cents"]
    ), "the buckets must exhaust the tender plus the carried credit and nothing more"

    agreement = scenario.read_agreement()
    assert_fields(
        agreement,
        periods_paid=2,
        rent_applied_cents=10154,
        partial_credit_cents=1838,
        late_fee_paid_cents=508,
        late_fee_balance_cents=0,
        reinstatement_fee_paid_cents=500,
        reinstatement_fee_balance_cents=0,
        payment_status=PaymentStatus.CURRENT,
        collections_stage=CollectionsStage.NONE,
        current_period_due_at="2026-08-22T00:00:00Z",
    )

    windows = world.windows(scenario.agreement_id)
    assert len(windows) == 1, f"expected exactly one reinstatement window, got {len(windows)}"
    assert windows[0]["status"] == WindowStatus.USED, (
        f"the cured window must be USED, got {windows[0]['status']}"
    )


def test_the_per_period_rate_is_rounded_up_before_it_is_multiplied(world):
    """Rounding the rate up first pushes the disclosed subtotal above the target total.

    PRD: Seventh, `rent_subtotal_cents` is `renewal_rate_cents` multiplied by `renewal_count` — the per-period rate is rounded up first and only then multiplied, so the disclosed subtotal ordinarily exceeds the target total; summing first and rounding afterwards is not permitted.

    Design: Difficulty/combinatorial_formula/pricing_ceil_rate_before_multiply_inflates_disclosed_subtotal
    """
    scenario = build_tx_floor(world)

    agreement = world.sign(scenario.customer_id, scenario.unit_id, TermType.WEEKLY, 52)
    assert_pricing(
        agreement,
        adjusted_cash_price_cents=W52_ADJUSTED_CASH_PRICE_CENTS,
        renewal_rate_cents=W52_RENEWAL_RATE_CENTS,
        rent_subtotal_cents=W52_RENT_SUBTOTAL_CENTS,
        processing_fee_cents=W52_PROCESSING_FEE_CENTS,
        total_of_payments_cents=W52_TOTAL_OF_PAYMENTS_CENTS,
        monthly_equivalent_rate_cents=W52_MONTHLY_EQUIVALENT_CENTS,
    )
    assert agreement["rent_subtotal_cents"] > TARGET_TOTAL_CENTS, (
        "rounding the rate up before multiplying must inflate the subtotal above "
        f"the {TARGET_TOTAL_CENTS} cent target total"
    )
    assert_signing_anchors_unset(agreement)
    assert_fields(
        agreement,
        payment_status=PaymentStatus.CURRENT,
        possession_status=PossessionStatus.PENDING_DELIVERY,
    )
    assert scenario.read_unit()["status"] == UnitStatus.RESERVED


def test_the_disclosure_derives_the_cost_of_renting_rather_than_buying(world):
    """The regulator's figure is the gap between the total of payments and the cash price.

    PRD: It reports the agreement's `agreement_id`, `term_type`, `renewal_count`, `adjusted_cash_price_cents`, `renewal_rate_cents`, `rent_subtotal_cents`, `processing_fee_cents`, `total_of_payments_cents`, `monthly_equivalent_rate_cents`, the jurisdiction's `early_purchase_formula` and its `state_code`, plus one derived figure computed nowhere else: `cost_of_rental_cents`, the amount by which `total_of_payments_cents` exceeds `adjusted_cash_price_cents`.

    Design: Difficulty/combinatorial_formula/pricing_ceil_rate_before_multiply_inflates_disclosed_subtotal
    """
    scenario = build_tx_floor(world)
    agreement = world.sign(scenario.customer_id, scenario.unit_id, TermType.WEEKLY, 52)

    disclosure = world.disclosure(agreement["id"])
    assert_fields(
        disclosure,
        agreement_id=agreement["id"],
        term_type=TermType.WEEKLY,
        renewal_count=52,
        adjusted_cash_price_cents=W52_ADJUSTED_CASH_PRICE_CENTS,
        renewal_rate_cents=W52_RENEWAL_RATE_CENTS,
        rent_subtotal_cents=W52_RENT_SUBTOTAL_CENTS,
        processing_fee_cents=W52_PROCESSING_FEE_CENTS,
        total_of_payments_cents=W52_TOTAL_OF_PAYMENTS_CENTS,
        monthly_equivalent_rate_cents=W52_MONTHLY_EQUIVALENT_CENTS,
        early_purchase_formula=PayoffFormula.PCT_OF_REMAINING,
        state_code="TX",
        cost_of_rental_cents=W52_COST_OF_RENTAL_CENTS,
    )
    assert (
        disclosure["total_of_payments_cents"] - disclosure["adjusted_cash_price_cents"]
        == disclosure["cost_of_rental_cents"]
    ), "the cost of rental is exactly the excess of the total over the cash price"


def test_the_processing_fee_is_five_percent_of_the_rent_subtotal_alone(world):
    """The fee base is the subtotal before any fee is folded in, with no iteration.

    PRD: Eighth, `processing_fee_cents` is the smaller of the jurisdiction's `processing_fee_max_cents` and five percent of `rent_subtotal_cents` rounded half up; the base is the rent subtotal as it stands **before** any fee is folded in, no fixed-point iteration is performed, and a jurisdiction whose cap is zero simply never charges the fee.

    Design: Difficulty/combinatorial_formula/processing_fee_base_pinned_to_rent_subtotal_not_total
    """
    scenario = build_tx_floor(world, serials=("SN-TX-0002",), category=Category.APPLIANCE)
    assert scenario.unit["cash_price_cents"] == WASHER_CASH_PRICE_CENTS

    agreement = world.sign(scenario.customer_id, scenario.unit_id, TermType.MONTHLY, 12)
    assert_pricing(
        agreement,
        adjusted_cash_price_cents=WASHER_CASH_PRICE_CENTS,
        renewal_rate_cents=M12_RENEWAL_RATE_CENTS,
        rent_subtotal_cents=M12_RENT_SUBTOTAL_CENTS,
        processing_fee_cents=M12_PROCESSING_FEE_CENTS,
        total_of_payments_cents=M12_TOTAL_OF_PAYMENTS_CENTS,
        monthly_equivalent_rate_cents=M12_RENEWAL_RATE_CENTS,
    )
    assert agreement["total_of_payments_cents"] != FEE_ON_THE_GRAND_TOTAL_CENTS, (
        "charging five percent of the grand total instead of the rent subtotal would "
        f"disclose {FEE_ON_THE_GRAND_TOTAL_CENTS} cents"
    )


def test_a_monthly_terms_monthly_equivalent_is_simply_its_renewal_rate(world):
    """No week-to-month conversion happens on a term already billed monthly.

    PRD: Tenth, `monthly_equivalent_rate_cents` is, for a `WEEKLY` agreement, `renewal_rate_cents` multiplied by 52, divided by 12 and rounded half up; for a `MONTHLY` agreement it is simply `renewal_rate_cents`.

    Design: Difficulty/combinatorial_formula/processing_fee_base_pinned_to_rent_subtotal_not_total
    """
    scenario = build_tx_floor(world, serials=("SN-TX-0002",), category=Category.APPLIANCE)
    agreement = world.sign(scenario.customer_id, scenario.unit_id, TermType.MONTHLY, 12)

    assert_fields(
        agreement,
        term_type=TermType.MONTHLY,
        renewal_rate_cents=M12_RENEWAL_RATE_CENTS,
        monthly_equivalent_rate_cents=M12_RENEWAL_RATE_CENTS,
    )

    disclosure = world.disclosure(agreement["id"])
    assert_fields(
        disclosure,
        renewal_rate_cents=M12_RENEWAL_RATE_CENTS,
        rent_subtotal_cents=M12_RENT_SUBTOTAL_CENTS,
        processing_fee_cents=M12_PROCESSING_FEE_CENTS,
        total_of_payments_cents=M12_TOTAL_OF_PAYMENTS_CENTS,
        monthly_equivalent_rate_cents=M12_RENEWAL_RATE_CENTS,
    )
