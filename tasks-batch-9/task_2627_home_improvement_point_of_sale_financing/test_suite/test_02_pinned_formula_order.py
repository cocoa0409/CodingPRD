"""Formulas whose evaluation order, not just whose inputs, is pinned.

Three orderings are exercised here: the component-wise composition of the final
merchant discount with its three independent roundings, the six-step reserve
target whose gap reads a volume that includes the very draw being settled, and
the instant decision's nested minimum over the income ceiling and the tier cap.
Each rejected alternative ordering is named alongside the figure it would give.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.assertions import assert_reason_codes, bps_of, assert_fields, round_half_up

FIRST_DRAW_CENTS = 1000050
SECOND_DRAW_CENTS = 1400000
NEGOTIATED_DISCOUNT_BPS = 449
NEXT_DAY_SURCHARGE_BPS = 75
TRADE_HOLDBACK_BPS = 500
STANDARD_TARGET_RATE_BPS = 400
PER_DRAW_CEILING_BPS = 1500

#: round_half_up(1000050 * 449 / 10000) == 44902.245 -> 44902
BASE_COMPONENT_CENTS = 44902
#: round_half_up(1000050 * 75 / 10000) == 7500.375 -> 7500
SPEED_COMPONENT_CENTS = 7500
#: 44902 + 7500 - 0
FIRST_DRAW_DISCOUNT_CENTS = 52402
#: the rejected single rounding of the collapsed 524 bps: 52402.62 -> 52403
COLLAPSED_RATE_DISCOUNT_CENTS = 52403
#: 1000050 - 52402 - 40002
FIRST_DRAW_NET_CENTS = 907646
FIRST_DRAW_HOLDBACK_CENTS = 40002

#: 1000050 + 1400000, the trailing-180-day volume INCLUDING the draw being settled
TRAILING_VOLUME_CENTS = 2400050
#: round_half_up(2400050 * 400 / 10000) == 96002
SECOND_TARGET_CENTS = 96002
#: 96002 - 40002
RESERVE_GAP_CENTS = 56000
#: round_half_up(1400000 * 500 / 10000)
BASE_WITHHOLD_CENTS = 70000
#: round_half_up(1400000 * 1500 / 10000)
PER_DRAW_CEILING_CENTS = 210000
#: 1400000 * 449 / 10000, exact, with no speed surcharge on STANDARD_3DAY
SECOND_DRAW_DISCOUNT_CENTS = 62860
#: 1400000 - 62860 - 56000
SECOND_DRAW_NET_CENTS = 1281140


def _first_draw_settled(api, releases=(3000,), verify=(0,)):
    """Lay out the named milestones, verify them, then settle a NEXT_DAY draw of 1000050."""
    scenario = S.project_with_milestones(api, releases=releases, verify=verify)
    S.request_draw(api, scenario, FIRST_DRAW_CENTS, 0, "NEXT_DAY")
    return scenario, S.settle_draw(api, scenario)


def _second_draw_settled(api):
    """Settle a second STANDARD_3DAY draw of 1400000 against the second verified milestone."""
    scenario, first = _first_draw_settled(api, releases=(3000, 4000), verify=(0, 1))
    assert first["holdback_withheld_cents"] == FIRST_DRAW_HOLDBACK_CENTS, (
        "The first draw must leave 40002 cents of reserve behind"
    )
    S.request_draw(api, scenario, SECOND_DRAW_CENTS, 1, "STANDARD_3DAY")
    return scenario, S.settle_draw(api, scenario)


def _enrolled_program(api):
    """An APPROVED ROOFING merchant with an ACTIVE enrollment over the clock date."""
    return S.enrolled_merchant(api)


def _decide(api, scenario, consumer, ticket_cents=C.CANONICAL_TICKET_CENTS):
    """Register one homeowner and file a point-of-sale application for an instant decision."""
    homeowner = S.register_consumer(api, scenario.merchant_id, **consumer)
    return get_success_data(
        api.create_credit_application(
            F.credit_application_payload(
                scenario.merchant_id,
                homeowner["id"],
                scenario.plan_id,
                project_amount_cents=ticket_cents,
            ),
            scenario.as_merchant,
        )
    )


def test_final_discount_is_the_sum_of_three_independently_rounded_components(api):
    """The billed discount is base plus speed minus credit, each rounded on its own.

    PRD: "The composition of these three rates into `merchant_discount_cents` is pinned component-wise, with three independent roundings."

    Design: Difficulty/combinatorial_formula/settlement_discount_component_wise_rounding_order_pinned
    """
    _scenario, settled = _first_draw_settled(api)

    assert bps_of(FIRST_DRAW_CENTS, NEGOTIATED_DISCOUNT_BPS) == BASE_COMPONENT_CENTS
    assert bps_of(FIRST_DRAW_CENTS, NEXT_DAY_SURCHARGE_BPS) == SPEED_COMPONENT_CENTS
    assert BASE_COMPONENT_CENTS + SPEED_COMPONENT_CENTS == FIRST_DRAW_DISCOUNT_CENTS
    assert_fields(
        settled,
        effective_discount_bps=NEGOTIATED_DISCOUNT_BPS,
        volume_tier_credit_bps=0,
        merchant_discount_cents=FIRST_DRAW_DISCOUNT_CENTS,
    )


def test_collapsing_the_rates_before_one_rounding_is_rejected_by_a_single_cent(api):
    """Rounding the summed 524 bps once would bill 52403; the pinned order bills 52402.

    PRD: "Collapsing the three rates into one sum and rounding once, or rounding the rate sum to a whole percent before applying it, both produce observably different figures and must not be used."

    Design: Difficulty/combinatorial_formula/settlement_discount_component_wise_rounding_order_pinned
    """
    _scenario, settled = _first_draw_settled(api)

    collapsed = bps_of(FIRST_DRAW_CENTS, NEGOTIATED_DISCOUNT_BPS + NEXT_DAY_SURCHARGE_BPS)
    assert collapsed == COLLAPSED_RATE_DISCOUNT_CENTS, "The rejected ordering must give 52403"
    assert settled["merchant_discount_cents"] == FIRST_DRAW_DISCOUNT_CENTS
    assert settled["merchant_discount_cents"] != collapsed
    assert settled["net_settlement_cents"] == FIRST_DRAW_NET_CENTS


def test_second_draw_holdback_is_the_reserve_gap_from_the_six_step_target(api):
    """The withhold is the smallest of base rate, reserve gap and per-draw ceiling.

    PRD: "Sixth, `holdback_withheld_cents` is the smallest of the base withholding, the gap and the per-draw ceiling, taken exactly with no further rounding."

    Design: Difficulty/combinatorial_formula/holdback_reserve_target_six_step_evaluation_order_pinned
    """
    scenario, settled = _second_draw_settled(api)

    assert bps_of(TRAILING_VOLUME_CENTS, STANDARD_TARGET_RATE_BPS) == SECOND_TARGET_CENTS
    assert SECOND_TARGET_CENTS - FIRST_DRAW_HOLDBACK_CENTS == RESERVE_GAP_CENTS
    assert bps_of(SECOND_DRAW_CENTS, TRADE_HOLDBACK_BPS) == BASE_WITHHOLD_CENTS
    assert bps_of(SECOND_DRAW_CENTS, PER_DRAW_CEILING_BPS) == PER_DRAW_CEILING_CENTS
    assert settled["holdback_withheld_cents"] == min(
        BASE_WITHHOLD_CENTS, RESERVE_GAP_CENTS, PER_DRAW_CEILING_CENTS
    )
    assert settled["holdback_withheld_cents"] == RESERVE_GAP_CENTS
    merchant = S.read_merchant(api, scenario.merchant_id)
    assert_fields(
        merchant,
        risk_tier="STANDARD",
        holdback_target_cents=SECOND_TARGET_CENTS,
        holdback_reserve_cents=FIRST_DRAW_HOLDBACK_CENTS + RESERVE_GAP_CENTS,
        reserve_coverage_bps=10000,
    )


def test_holdback_rejects_the_cap_before_gap_and_excluded_draw_orderings(api):
    """Neither the loose per-draw ceiling nor a target that excludes this draw may decide the withhold.

    PRD: "Computing the target from volume that excludes the current draw would make a new merchant's first draw withhold nothing forever; applying the per-draw ceiling before the target gap would yield the base rate whenever the ceiling is loose; and rounding the target after subtracting the existing reserve rather than before gives a different figure again."

    Design: Difficulty/combinatorial_formula/holdback_reserve_target_six_step_evaluation_order_pinned
    """
    _scenario, settled = _second_draw_settled(api)

    # Excluding this draw: target 40002 - reserve 40002 == a zero gap.
    excluded_draw_target = bps_of(FIRST_DRAW_CENTS, STANDARD_TARGET_RATE_BPS)
    assert max(0, excluded_draw_target - FIRST_DRAW_HOLDBACK_CENTS) == 0
    assert settled["holdback_withheld_cents"] != 0
    # Ceiling before gap: min(70000, 210000) == the base rate.
    assert min(BASE_WITHHOLD_CENTS, PER_DRAW_CEILING_CENTS) == BASE_WITHHOLD_CENTS
    assert settled["holdback_withheld_cents"] != BASE_WITHHOLD_CENTS
    assert settled["holdback_withheld_cents"] == RESERVE_GAP_CENTS


def test_second_draw_net_settlement_and_principal_follow_the_pinned_figures(api):
    """The contractor is paid the funded amount less the billed discount and the gap withhold.

    PRD: "`net_settlement_cents`, the money that actually reaches the contractor, is `funded_amount_cents` reduced by `merchant_discount_cents` and reduced again by `holdback_withheld_cents`."

    Design: Difficulty/combinatorial_formula/holdback_reserve_target_six_step_evaluation_order_pinned
    """
    scenario, settled = _second_draw_settled(api)

    assert bps_of(SECOND_DRAW_CENTS, NEGOTIATED_DISCOUNT_BPS) == SECOND_DRAW_DISCOUNT_CENTS
    assert_fields(
        settled,
        funded_amount_cents=SECOND_DRAW_CENTS,
        volume_tier_credit_bps=0,
        merchant_discount_cents=SECOND_DRAW_DISCOUNT_CENTS,
        holdback_withheld_cents=RESERVE_GAP_CENTS,
        net_settlement_cents=SECOND_DRAW_NET_CENTS,
    )
    assert (
        SECOND_DRAW_CENTS - SECOND_DRAW_DISCOUNT_CENTS - RESERVE_GAP_CENTS
        == SECOND_DRAW_NET_CENTS
    )
    loan = S.read_loan(api, scenario.loan_id)
    assert loan["principal_balance_cents"] == TRAILING_VOLUME_CENTS


def test_instant_decision_approves_when_the_income_arm_of_the_minimum_binds(api):
    """A 780 score on 9600000 income lands under the tier cap, so the income ceiling is the line.

    PRD: "The consumer's `annual_income_cents` is multiplied by the tier's income factor in basis points, divided by ten thousand and rounded half up; the lower of that figure and the tier's cap is the credit ceiling."

    Design: Difficulty/combinatorial_formula/instant_decision_nested_min_over_tier_and_income_ceiling
    """
    scenario = _enrolled_program(api)

    application = _decide(
        api,
        scenario,
        {"full_name": "Alma Reyes", "ssn_last4": "1180", "annual_income_cents": 9600000,
         "fico_score": 780, "state_code": "TX"},
    )

    # min(round_half_up(9600000 * 6000 / 10000) == 5760000, tier cap 7500000) == 5760000
    assert min(bps_of(9600000, 6000), 7500000) == 5760000
    assert_fields(
        application,
        decision="APPROVED",
        approved_limit_cents=5760000,
        decision_dti_bps=round_half_up(3500000 * C.BPS_ONE, 9600000),
        disclosure_status="NOT_SENT",
    )
    assert application["decision_dti_bps"] == 3646
    assert_reason_codes(application, "WITHIN_LIMIT")
    # Fourteen days after the decision instant of 2026-08-01T00:00:00Z.
    assert application["offer_expires_at"].startswith("2026-08-15T00:00:00")


def test_instant_decision_counter_offers_when_the_tier_cap_arm_of_the_minimum_binds(api):
    """A 680 score on 20000000 income is capped by its tier, so the ticket exceeds the line.

    PRD: "When the ticket exceeds the ceiling but the ceiling is at least 200000 cents, `decision` becomes `COUNTER_OFFERED` with `approved_limit_cents` set to the ceiling and `decision_reason_codes` written as the single code `LIMIT_BELOW_TICKET`; the homeowner is being offered less than they asked for."

    Design: Difficulty/combinatorial_formula/instant_decision_nested_min_over_tier_and_income_ceiling
    """
    scenario = _enrolled_program(api)

    application = _decide(
        api,
        scenario,
        {"full_name": "Boris Kane", "ssn_last4": "2291", "annual_income_cents": 20000000,
         "fico_score": 680, "state_code": "TX"},
    )

    # min(round_half_up(20000000 * 3000 / 10000) == 6000000, tier cap 3000000) == 3000000
    assert min(bps_of(20000000, 3000), 3000000) == 3000000
    assert_fields(
        application,
        decision="COUNTER_OFFERED",
        approved_limit_cents=3000000,
        decision_dti_bps=round_half_up(3500000 * C.BPS_ONE, 20000000),
        disclosure_status="NOT_SENT",
    )
    assert application["decision_dti_bps"] == 1750
    assert_reason_codes(application, "LIMIT_BELOW_TICKET")


def test_instant_decision_declines_below_the_score_floor_without_computing_the_ratio(api):
    """A 619 score short-circuits the whole ladder, leaving the ratio at zero.

    PRD: "If `fico_score` is below 620, the application is declined outright: `decision` becomes `DECLINED`, `approved_limit_cents` stays at zero, `decision_reason_codes` is written as the single code `FICO_BELOW_FLOOR`, and `decision_dti_bps` is left at zero because the debt-to-income ratio is never computed when the score floor fails."

    Design: Difficulty/combinatorial_formula/instant_decision_nested_min_over_tier_and_income_ceiling
    """
    scenario = _enrolled_program(api)

    application = _decide(
        api,
        scenario,
        {"full_name": "Cleo Vance", "ssn_last4": "3302", "annual_income_cents": 9600000,
         "fico_score": 619, "state_code": "TX"},
    )

    assert_fields(
        application,
        decision="DECLINED",
        approved_limit_cents=0,
        decision_dti_bps=0,
        disclosure_status="NOT_SENT",
    )
    assert_reason_codes(application, "FICO_BELOW_FLOOR")
    # The ratio that was never computed would have been an affordable 3646 bps.
    assert round_half_up(3500000 * C.BPS_ONE, 9600000) == 3646
