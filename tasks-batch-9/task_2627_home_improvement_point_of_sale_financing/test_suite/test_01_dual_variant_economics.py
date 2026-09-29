"""The two money variants that live side by side on one row.

A funding draw prices itself twice — once at write time from plan and trade
rates, once at settlement from the negotiated rate, the speed surcharge and the
six-step reserve target — and a deferred-interest loan account quotes two
payoffs at the same instant, one that waives the accrual and one that charges
it.  Every figure below is the exact integer the pinned formulas yield.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.assertions import assert_fields, assert_unchanged, bps_of

# ─── The canonical draw and the figures both variants produce ─────────

FUNDED_CENTS = 1000050
PLAN_DISCOUNT_BPS = 525
NEGOTIATED_DISCOUNT_BPS = 449
NEXT_DAY_SURCHARGE_BPS = 75
TRADE_HOLDBACK_BPS = 500
STANDARD_TARGET_RATE_BPS = 400

#: round_half_up(1000050 * 525 / 10000) == 52502.625 -> 52503
PROVISIONAL_DISCOUNT_CENTS = 52503
#: round_half_up(1000050 * 500 / 10000) == 50002.5 -> 50003
PROVISIONAL_HOLDBACK_CENTS = 50003
#: 1000050 - 52503 - 50003
PROVISIONAL_NET_CENTS = 897544

#: round_half_up(1000050 * 449 / 10000) == 44902 plus round_half_up(1000050 * 75 / 10000) == 7500
FINAL_DISCOUNT_CENTS = 52402
#: min(base 50003, gap 40002 - 0, per-draw ceiling 150008) == 40002
FINAL_HOLDBACK_CENTS = 40002
#: 1000050 - 52402 - 40002
FINAL_NET_CENTS = 907646
#: 907646 - 897544
RECONCILIATION_DELTA_CENTS = 10102

# ─── The two-draw promotional loan and its accrual ────────────────────

SECOND_DRAW_CENTS = 1400000
#: 1000050 + 1400000
PRINCIPAL_AFTER_TWO_DRAWS = 2400050
#: (1000050 * 2699 * 26 + 2400050 * 2699 * 330) / (10000 * 365) == 604884.943... -> 604885
ACCRUED_DEFERRED_CENTS = 604885
#: principal alone, because a timely payoff waives the accrual
PROMO_PAYOFF_CENTS = 2400050
#: 2400050 + 0 capitalized + 604885 accrued
STANDARD_PAYOFF_CENTS = 3004935


def _draw_requested_at_startup_clock(api):
    """One VERIFIED milestone at 3000 bps and a NEXT_DAY draw of 1000050 cents on it."""
    scenario = S.project_with_milestones(api, releases=(3000,), verify=(0,))
    assert scenario.project["max_fundable_now_cents"] == 1050000, (
        "3500000 * 3000 bps must leave 1050000 cents of headroom"
    )
    draw = S.request_draw(api, scenario, FUNDED_CENTS, 0, "NEXT_DAY")
    return scenario, draw


def _two_draw_promotional_loan(api):
    """Settle 1000050 on 2026-08-10 and 1400000 on 2026-09-05, then stand on 2027-08-01."""
    scenario = S.project_with_milestones(api, releases=(3000, 4000), verify=(0, 1))
    S.set_clock(api, "2026-08-10T00:00:00Z")
    S.request_draw(api, scenario, FUNDED_CENTS, 0, "NEXT_DAY")
    S.settle_draw(api, scenario)
    S.set_clock(api, "2026-09-05T00:00:00Z")
    S.request_draw(api, scenario, SECOND_DRAW_CENTS, 1, "STANDARD_3DAY")
    S.settle_draw(api, scenario)
    S.set_clock(api, "2027-08-01T00:00:00Z")
    return scenario


def test_draw_creation_prices_the_provisional_variant_at_plan_and_trade_rates(api):
    """A created draw carries the write-time estimate built from the plan rate and the trade rate.

    PRD: "The provisional view deliberately uses only plan-level and trade-level rates: `provisional_discount_cents` is `funded_amount_cents` multiplied by the promotion plan's `merchant_discount_bps`, divided by ten thousand and rounded half up; `provisional_holdback_cents` is `funded_amount_cents` multiplied by the trade rule's `holdback_pct_bps`, divided by ten thousand and rounded half up; and `provisional_net_settlement_cents` is `funded_amount_cents` reduced by `provisional_discount_cents` and reduced again by `provisional_holdback_cents`."

    Design: Difficulty/dual_variant_calc/draw_provisional_versus_final_settlement_divergence
    """
    _scenario, draw = _draw_requested_at_startup_clock(api)

    assert bps_of(FUNDED_CENTS, PLAN_DISCOUNT_BPS) == PROVISIONAL_DISCOUNT_CENTS
    assert bps_of(FUNDED_CENTS, TRADE_HOLDBACK_BPS) == PROVISIONAL_HOLDBACK_CENTS
    assert_fields(
        draw,
        status="REQUESTED",
        funded_amount_cents=FUNDED_CENTS,
        provisional_discount_cents=PROVISIONAL_DISCOUNT_CENTS,
        provisional_holdback_cents=PROVISIONAL_HOLDBACK_CENTS,
        provisional_net_settlement_cents=PROVISIONAL_NET_CENTS,
    )


def test_settlement_final_variant_diverges_from_the_provisional_estimate_on_one_row(api):
    """Settlement writes final figures that differ from the provisional estimate frozen on the same draw.

    PRD: "The gap between this estimate and what actually settles is the reconciliation figure servicing reports back to the contractor."

    Design: Difficulty/dual_variant_calc/draw_provisional_versus_final_settlement_divergence
    """
    scenario, created = _draw_requested_at_startup_clock(api)

    settled = S.settle_draw(api, scenario)

    assert_fields(
        settled,
        status="SETTLED",
        funded_amount_cents=FUNDED_CENTS,
        effective_discount_bps=NEGOTIATED_DISCOUNT_BPS,
        volume_tier_credit_bps=0,
        merchant_discount_cents=FINAL_DISCOUNT_CENTS,
        holdback_withheld_cents=FINAL_HOLDBACK_CENTS,
        net_settlement_cents=FINAL_NET_CENTS,
    )
    # The provisional estimate is frozen: both variants stand on the settled row.
    assert_unchanged(
        created,
        settled,
        "provisional_discount_cents",
        "provisional_holdback_cents",
        "provisional_net_settlement_cents",
    )
    assert settled["merchant_discount_cents"] != settled["provisional_discount_cents"]
    assert settled["holdback_withheld_cents"] != settled["provisional_holdback_cents"]
    assert (
        settled["net_settlement_cents"] - settled["provisional_net_settlement_cents"]
        == RECONCILIATION_DELTA_CENTS
    )


def test_settlement_writes_the_reserve_target_from_the_final_holdback_only(api):
    """The merchant ledger takes the final variant's holdback, not the provisional estimate.

    PRD: "On the merchant, `funded_volume_cents` rises by `funded_amount_cents`, `holdback_reserve_cents` rises by `holdback_withheld_cents`, `holdback_target_cents` is written as the target computed at step two, and `reserve_coverage_bps` is recomputed as `holdback_reserve_cents` multiplied by ten thousand, divided by `holdback_target_cents` and rounded half up — or as exactly ten thousand when `holdback_target_cents` is zero, since a merchant with no target is trivially fully covered."

    Design: Difficulty/dual_variant_calc/draw_provisional_versus_final_settlement_divergence
    """
    scenario, _created = _draw_requested_at_startup_clock(api)

    S.settle_draw(api, scenario)

    # An unseasoned merchant sits at STANDARD: 1000050 * 400 bps == 40002 == the target.
    assert bps_of(FUNDED_CENTS, STANDARD_TARGET_RATE_BPS) == FINAL_HOLDBACK_CENTS
    merchant = S.read_merchant(api, scenario.merchant_id)
    assert_fields(
        merchant,
        risk_tier="STANDARD",
        funded_volume_cents=FUNDED_CENTS,
        holdback_reserve_cents=FINAL_HOLDBACK_CENTS,
        holdback_target_cents=FINAL_HOLDBACK_CENTS,
        reserve_coverage_bps=10000,
    )
    assert merchant["holdback_reserve_cents"] != PROVISIONAL_HOLDBACK_CENTS
    loan = S.read_loan(api, scenario.loan_id)
    assert_fields(loan, principal_balance_cents=FUNDED_CENTS, total_funded_cents=FUNDED_CENTS)


def test_promo_and_standard_payoff_variants_diverge_by_the_whole_deferred_accrual(api):
    """On the last promotional day the account quotes two payoffs differing by the accrual exactly.

    PRD: "`standard_payoff_cents` is the post-expiration-variant payoff and equals `principal_balance_cents` plus `capitalized_interest_cents` plus `accrued_deferred_interest_cents`."

    Design: Difficulty/dual_variant_calc/loan_promo_satisfied_versus_capitalized_payoff_divergence
    """
    scenario = _two_draw_promotional_loan(api)

    loan = S.read_loan(api, scenario.loan_id)

    assert_fields(
        loan,
        promo_status="PROMO_ACTIVE",
        promo_expires_on="2027-08-01",
        apr_bps=2699,
        principal_balance_cents=PRINCIPAL_AFTER_TWO_DRAWS,
        capitalized_interest_cents=0,
        waived_interest_cents=0,
        accrued_deferred_interest_cents=ACCRUED_DEFERRED_CENTS,
        deferred_interest_at_risk_cents=ACCRUED_DEFERRED_CENTS,
        promo_payoff_cents=PROMO_PAYOFF_CENTS,
        standard_payoff_cents=STANDARD_PAYOFF_CENTS,
    )
    assert (
        loan["standard_payoff_cents"] - loan["promo_payoff_cents"] == ACCRUED_DEFERRED_CENTS
    )


def test_payment_during_the_promotion_applies_nothing_to_capitalized_interest(api):
    """A payoff posted while the promotion is live puts every cent against principal.

    PRD: "The first bucket, `applied_to_capitalized_interest_cents`, takes the lesser of `amount_cents` and the account's `capitalized_interest_cents`; while `promo_status` is `PROMO_ACTIVE` this bucket is necessarily zero, since accrued promotional interest is not payable — that is the entire point of a deferred-interest product."

    Design: Difficulty/dual_variant_calc/loan_promo_satisfied_versus_capitalized_payoff_divergence
    """
    scenario = _two_draw_promotional_loan(api)

    payment = get_success_data(
        api.create_payment(
            F.payment_payload(scenario.loan_id, PROMO_PAYOFF_CENTS), scenario.as_consumer
        )
    )

    assert_fields(
        payment,
        source_role="CONSUMER",
        posted_on="2027-08-01",
        applied_to_capitalized_interest_cents=0,
        applied_to_principal_cents=PROMO_PAYOFF_CENTS,
        resulting_principal_balance_cents=0,
    )


def test_paying_the_promo_variant_on_the_expiry_date_waives_the_capitalized_variant(api):
    """Clearing principal on the inclusive last promotional day forgives the whole accrual.

    PRD: "If the payment brings `principal_balance_cents` to zero on or before `promo_expires_on` — the boundary being inclusive, so a payment posted on the expiration date itself still wins the wager — the promotional dimension moves `PROMO_ACTIVE → PROMO_SATISFIED`: `waived_interest_cents` is written with the accrual standing at that instant, `accrued_deferred_interest_cents` and `deferred_interest_at_risk_cents` both drop to zero, `capitalized_interest_cents` stays at zero, and the repayment dimension moves `CURRENT → PAID_OFF`, with the consumer's `existing_program_debt_cents` and `active_loan_count` recomputed."

    Design: Difficulty/dual_variant_calc/loan_promo_satisfied_versus_capitalized_payoff_divergence
    """
    scenario = _two_draw_promotional_loan(api)

    get_success_data(
        api.create_payment(
            F.payment_payload(scenario.loan_id, PROMO_PAYOFF_CENTS), scenario.as_consumer
        )
    )

    loan = S.read_loan(api, scenario.loan_id)
    assert_fields(
        loan,
        promo_status="PROMO_SATISFIED",
        balance_status="PAID_OFF",
        principal_balance_cents=0,
        capitalized_interest_cents=0,
        waived_interest_cents=ACCRUED_DEFERRED_CENTS,
        accrued_deferred_interest_cents=0,
        deferred_interest_at_risk_cents=0,
        promo_payoff_cents=0,
    )
    # The capitalized variant was never charged: 3004935 would have been owed instead.
    assert loan["waived_interest_cents"] == STANDARD_PAYOFF_CENTS - PROMO_PAYOFF_CENTS
