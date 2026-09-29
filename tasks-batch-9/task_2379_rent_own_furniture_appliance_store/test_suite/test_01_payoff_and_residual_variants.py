"""Two figures that each have two lawful shapes: the early-purchase payoff and the residual.

The payoff base is chosen by the store's jurisdiction, so the same renter with the
same payment history owes two very different amounts on two otherwise identical
agreements. The residual is computed twice on one unit: once provisionally when the
goods come back and once finally when the technician grades them.
"""

from __future__ import annotations

from types import SimpleNamespace

from test_helpers import (
    AUSTIN_MAIN,
    CLOCK_EPOCH,
    DULUTH_MAIN,
    MN_CREW_A,
    SALES,
    TX_CREW_A,
    W52_ADJUSTED_CASH_PRICE_CENTS,
    W52_RENEWAL_RATE_CENTS,
    W52_TOTAL_OF_PAYMENTS_CENTS,
    ConditionGrade,
    DepreciationTier,
    InspectionStatus,
    LoyaltyTier,
    PaymentStatus,
    PayoffFormula,
    PossessionStatus,
    QuoteStatus,
    ResidualBasis,
    UnitStatus,
    assert_fields,
    assert_pricing,
    build_tx_floor,
    deliver_on,
    sign_on,
)

MN_TOTAL_OF_PAYMENTS_CENTS = 264004
RENT_APPLIED_AFTER_THREE_PERIODS = 3 * W52_RENEWAL_RATE_CENTS  # 15,231

TX_PRE_DISCOUNT_CENTS = 139575
TX_LOYALTY_DISCOUNT_CENTS = 6979
TX_PAYOFF_CENTS = 132596

MN_PRE_DISCOUNT_CENTS = 111623
MN_LOYALTY_DISCOUNT_CENTS = 5581
MN_PAYOFF_CENTS = 106042


def _two_jurisdictions_one_renter(world):
    """One renter holding two identical sofas, one in Texas and one in Minnesota.

    Both agreements are weekly over fifty-two renewals against a brand-new 120,000
    cent sofa, both are delivered on the first of the month, and each then takes
    three on-time renewal payments at the disclosed rate.
    """
    world.set_clock(CLOCK_EPOCH)
    tx_rule = world.seed_tx_rule()
    mn_rule = world.seed_mn_rule()

    tx_store = world.open_store(AUSTIN_MAIN, "TX", 1)
    mn_store = world.open_store(DULUTH_MAIN, "MN", 2)
    tx_unit = world.add_sofa(tx_store["id"], "SN-TX-0001")
    mn_unit = world.add_sofa(mn_store["id"], "SN-MN-0001")

    customer = world.onboard_dana()

    tx_agreement = world.sign(customer["id"], tx_unit["id"])
    mn_agreement = world.sign(customer["id"], mn_unit["id"])

    tx_crew = world.add_crew(tx_store["id"], TX_CREW_A)
    mn_crew = world.add_crew(mn_store["id"], MN_CREW_A)
    world.deliver(tx_agreement["id"], tx_crew["id"])
    world.deliver(mn_agreement["id"], mn_crew["id"])

    for _ in range(3):
        world.pay(tx_agreement["id"], W52_RENEWAL_RATE_CENTS)
    for _ in range(3):
        world.pay(mn_agreement["id"], W52_RENEWAL_RATE_CENTS)

    return SimpleNamespace(
        world=world,
        tx_rule=tx_rule,
        mn_rule=mn_rule,
        customer_id=customer["id"],
        tx_agreement_id=tx_agreement["id"],
        mn_agreement_id=mn_agreement["id"],
        tx_unit_id=tx_unit["id"],
        mn_unit_id=mn_unit["id"],
    )


def test_texas_payoff_keeps_the_markup_and_the_fee_inside_the_base(world):
    """A Texas payoff is a percentage of what is still owed on the disclosed total.

    PRD: Under `PCT_OF_REMAINING`, `pre_discount_cents` is the amount still owed under the disclosed total — `total_of_payments_cents` less `rent_applied_snapshot_cents` — multiplied by the jurisdiction's `early_purchase_pct` and rounded half up; the processing fee and the entire rental markup therefore remain in the base.

    Design: Difficulty/dual_variant_calc/early_purchase_payoff_pct_of_remaining_vs_cash_price_minus_credit
    """
    story = _two_jurisdictions_one_renter(world)

    agreement = world.get_agreement(story.tx_agreement_id)
    assert_fields(
        agreement,
        total_of_payments_cents=W52_TOTAL_OF_PAYMENTS_CENTS,
        rent_applied_cents=RENT_APPLIED_AFTER_THREE_PERIODS,
        periods_paid=3,
        payment_status=PaymentStatus.CURRENT,
    )

    quote = world.issue_quote(story.tx_agreement_id, headers=SALES)
    assert_fields(
        quote,
        agreement_id=story.tx_agreement_id,
        formula_applied=PayoffFormula.PCT_OF_REMAINING,
        rent_applied_snapshot_cents=RENT_APPLIED_AFTER_THREE_PERIODS,
        pre_discount_cents=TX_PRE_DISCOUNT_CENTS,
        loyalty_tier_snapshot=LoyaltyTier.GOLD,
        loyalty_discount_cents=TX_LOYALTY_DISCOUNT_CENTS,
        late_fee_component_cents=0,
        payoff_amount_cents=TX_PAYOFF_CENTS,
        status=QuoteStatus.OPEN,
        expires_at="2026-08-08T00:00:00Z",
    )
    assert (
        quote["pre_discount_cents"]
        - quote["loyalty_discount_cents"]
        + quote["late_fee_component_cents"]
        == quote["payoff_amount_cents"]
    ), "the payoff is the base less the loyalty discount plus the pinned fee component"


def test_minnesota_payoff_strips_the_markup_and_credits_rent_already_paid(world):
    """A Minnesota payoff starts from the depreciated cash price and credits rent back.

    PRD: Under `CASH_PRICE_MINUS_CREDIT`, `pre_discount_cents` is the depreciated `adjusted_cash_price_cents` less a rent credit, where the credit is `rent_applied_snapshot_cents` multiplied by the jurisdiction's `rent_credit_pct` and rounded half up; the result is floored at 0, and neither the markup nor the processing fee is in the base at all.

    Design: Difficulty/dual_variant_calc/early_purchase_payoff_pct_of_remaining_vs_cash_price_minus_credit
    """
    story = _two_jurisdictions_one_renter(world)

    mn_agreement = world.get_agreement(story.mn_agreement_id)
    assert_fields(
        mn_agreement,
        adjusted_cash_price_cents=W52_ADJUSTED_CASH_PRICE_CENTS,
        total_of_payments_cents=MN_TOTAL_OF_PAYMENTS_CENTS,
        rent_applied_cents=RENT_APPLIED_AFTER_THREE_PERIODS,
        periods_paid=3,
    )

    # Six on-time payments at 5,077 cents each carried the renter to 600 lifetime
    # points, so both quotes are discounted at the top tier.
    customer = world.get_customer(story.customer_id)
    assert_fields(
        customer, loyalty_points_lifetime=600, loyalty_tier=LoyaltyTier.GOLD
    )

    tx_quote = world.issue_quote(story.tx_agreement_id, headers=SALES)
    mn_quote = world.issue_quote(story.mn_agreement_id, headers=SALES)

    assert_fields(
        mn_quote,
        agreement_id=story.mn_agreement_id,
        formula_applied=PayoffFormula.CASH_PRICE_MINUS_CREDIT,
        rent_applied_snapshot_cents=RENT_APPLIED_AFTER_THREE_PERIODS,
        pre_discount_cents=MN_PRE_DISCOUNT_CENTS,
        loyalty_tier_snapshot=LoyaltyTier.GOLD,
        loyalty_discount_cents=MN_LOYALTY_DISCOUNT_CENTS,
        late_fee_component_cents=0,
        payoff_amount_cents=MN_PAYOFF_CENTS,
        status=QuoteStatus.OPEN,
        expires_at="2026-08-08T00:00:00Z",
    )
    assert (
        tx_quote["payoff_amount_cents"] - mn_quote["payoff_amount_cents"] == 26554
    ), "the same history under two formulas must diverge by the markup and the fee"


def _returned_but_not_yet_graded(world):
    """The canonical Texas sofa delivered, then voluntarily returned pending inspection."""
    scenario = deliver_on(sign_on(build_tx_floor(world)))
    world.start_return(scenario.agreement_id)
    inspections = world.inspections(agreement_id=scenario.agreement_id)
    assert len(inspections) == 1, (
        f"a return must open exactly one inspection, got {len(inspections)}"
    )
    return scenario, inspections[0]


def test_provisional_residual_assumes_one_notch_of_wear_and_no_deductions(world):
    """At return the unit is valued as if a rental's worth of wear had happened.

    PRD: In the provisional variant the grade factor is read from one notch **below** the unit's current `condition_grade` — the assumed wear of a completed rental, using the same ladder where a step below `GRADE_C` is still `GRADE_C` — and deductions are 0, because damage and missing parts are still unknown.

    Design: Difficulty/dual_variant_calc/unit_residual_provisional_at_return_vs_final_at_grading
    """
    scenario, inspection = _returned_but_not_yet_graded(world)

    assert_fields(
        inspection,
        agreement_id=scenario.agreement_id,
        unit_id=scenario.unit_id,
        status=InspectionStatus.PENDING,
        assessed_grade=None,
        depreciation_tier=DepreciationTier.TIER_1,
    )

    unit = scenario.read_unit()
    assert_fields(
        unit,
        status=UnitStatus.RETURNED_PENDING_GRADE,
        condition_grade=ConditionGrade.NEW,
        rent_cycle_count=0,
        residual_value_cents=96900,
        residual_valuation_basis=ResidualBasis.PROVISIONAL,
    )

    agreement = scenario.read_agreement()
    assert_fields(agreement, possession_status=PossessionStatus.RETURN_PENDING_INSPECTION)


def test_final_residual_replaces_the_assumption_with_the_assessed_grade(world):
    """Grading recomputes the residual from the real grade and the real deductions.

    PRD: The final residual uses the same product and the same next-cycle factor as the provisional one, but reads the grade factor from the submitted `assessed_grade` — which may be better or worse than the assumed step-down — and subtracts real deductions: `damage_deduction_cents` plus 2,500 cents for each missing part.

    Design: Difficulty/dual_variant_calc/unit_residual_provisional_at_return_vs_final_at_grading
    """
    scenario, inspection = _returned_but_not_yet_graded(world)
    assert scenario.read_unit()["residual_value_cents"] == 96900

    graded = world.grade(
        inspection["id"],
        ConditionGrade.GRADE_B,
        damage_deduction_cents=3000,
        missing_parts_count=1,
    )
    assert_fields(
        graded,
        status=InspectionStatus.GRADED,
        assessed_grade=ConditionGrade.GRADE_B,
        damage_deduction_cents=3000,
        missing_parts_count=1,
        final_residual_value_cents=74300,
        re_rent_rate_cents=3144,
        depreciation_tier=DepreciationTier.TIER_2,
    )

    unit = scenario.read_unit()
    assert_fields(
        unit,
        status=UnitStatus.AVAILABLE,
        condition_grade=ConditionGrade.GRADE_B,
        rent_cycle_count=1,
        residual_value_cents=74300,
        residual_valuation_basis=ResidualBasis.FINAL,
    )

    agreement = scenario.read_agreement()
    assert_fields(
        agreement,
        possession_status=PossessionStatus.RETURNED,
        payment_status=PaymentStatus.CLOSED,
    )
    assert_pricing(
        agreement,
        adjusted_cash_price_cents=W52_ADJUSTED_CASH_PRICE_CENTS,
        renewal_rate_cents=W52_RENEWAL_RATE_CENTS,
        rent_subtotal_cents=264004,
        processing_fee_cents=5000,
        total_of_payments_cents=W52_TOTAL_OF_PAYMENTS_CENTS,
        monthly_equivalent_rate_cents=22000,
    )
