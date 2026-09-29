"""Composite formulas: the weighted listing match score, the strike ledger's
per-contribution rounding, and the test-buy fee ladder."""

import pytest

from test_helpers import (
    ANALYST,
    ENFORCEMENT_STATUS_NONE,
    MONITOR_STATUS_FLAGGED,
    SELLER_STATUS_ACTIVE,
    TEST_BUY_STATUS_ORDERED,
    VIOLATION_TYPE_COUNTERFEIT,
    assert_all_sweep_counts_zero,
    assert_cents,
    assert_listing_screening,
    assert_instant_equals,
    assert_score_2dp,
    assert_score_4dp,
    assert_seller_strikes,
    assert_sweep_counts,
    assert_test_buy_pricing,
    conclude_investigation,
    create_border_seizure_investigation,
    create_listing,
    create_recorded_recordation,
    match_score,
    read_brand,
    read_seller,
    run_sweep,
    screen_payload,
    set_clock,
    setup_claim,
    setup_enrolled_brand,
    setup_removed_takedown,
    setup_second_removal_on_same_seller,
    strike_contribution,
    strike_total,
    submit_investigation_evidence,
    test_buy_payload,
    test_buy_pricing,
    validate_success,
)


def test_match_score_composes_three_weighted_terms_and_a_zero_risk_boost(api):
    """PRD §3.4: "Second, three weighted terms are accumulated at full precision, with weights that sum to exactly 1.00: the image sub-score contributes forty-five hundredths of its value, the text sub-score contributes thirty-five hundredths of its value, and the price deviation factor contributes twenty hundredths of its value."
    PRD §3.4: "Otherwise the boost is 0.00."
    PRD §3.4: "Three worked screens make the arithmetic unambiguous. With a reference of 10000 cents and a price of 3000 cents, an image sub-score of 0.92 and a text sub-score of 0.88 with no boost accumulate 0.414 plus 0.308 plus 0.14, giving a `match_score` of 0.8620, a `FLAGGED` verdict and a `COUNTERFEIT` classification."
    PRD §3.4: "Every screen increments the listing's `version` by 1, whether it flags or clears."

    Design: Difficulty/combinatorial_formula/listing_match_score_composes_three_weighted_factors_and_a_risk_boost
    """
    ctx = setup_enrolled_brand(api, clock="2026-08-03T09:00:00Z")
    seller = validate_success(
        api.create_seller({"marketplace_code": "AMZ", "seller_ref": "A1SELLER",
                           "legal_name": "Nightmarket Trading Ltd", "jurisdiction": "CN"},
                          headers=ANALYST), 201)
    assert_seller_strikes(seller, 0.00, 0.00, SELLER_STATUS_ACTIVE)
    listing = create_listing(api, ctx["brand"]["id"], seller["id"], price_cents=3000)
    assert listing["version"] == 1, f"A fresh listing starts at version 1, got {listing['version']}"

    screened = validate_success(
        api.screen_listing(listing["id"], screen_payload(0.92, 0.88), headers=ANALYST), 200)

    assert_listing_screening(screened, 0.92, 0.88, 0.7000, 0.8620,
                             MONITOR_STATUS_FLAGGED, VIOLATION_TYPE_COUNTERFEIT)
    assert_score_4dp(screened["match_score"], match_score(0.92, 0.88, 0.7000), "match_score")
    assert screened["enforcement_status"] == ENFORCEMENT_STATUS_NONE, (
        f"Screening never touches the enforcement dimension, got {screened['enforcement_status']}")
    assert screened["version"] == 2, f"Expected version 2 after one screen, got {screened['version']}"


def test_price_deviation_term_carries_exactly_twenty_hundredths_of_its_weight(api):
    """PRD §3.4: "A reference of 10000 cents against a price of 3000 cents gives 0.7000; against a price of 9500 cents it gives 0.0500; against a price of 12000 cents it gives 0.0000."
    PRD §3.4: "Second, three weighted terms are accumulated at full precision, with weights that sum to exactly 1.00: the image sub-score contributes forty-five hundredths of its value, the text sub-score contributes thirty-five hundredths of its value, and the price deviation factor contributes twenty hundredths of its value."
    PRD §3.4: "Otherwise, if `image_match_score` is at least 0.85, `violation_type` is `COUNTERFEIT`."

    Design: Difficulty/combinatorial_formula/listing_match_score_composes_three_weighted_factors_and_a_risk_boost
    """
    ctx = setup_enrolled_brand(api, clock="2026-08-03T09:00:00Z")
    seller = validate_success(
        api.create_seller({"marketplace_code": "AMZ", "seller_ref": "A1SELLER",
                           "legal_name": "Nightmarket Trading Ltd"}, headers=ANALYST), 201)
    listing = create_listing(api, ctx["brand"]["id"], seller["id"], price_cents=9500)

    screened = validate_success(
        api.screen_listing(listing["id"], screen_payload(0.92, 0.88), headers=ANALYST), 200)

    # 0.414 plus 0.308 plus 0.20 * 0.0500 accumulates 0.7320.
    assert_listing_screening(screened, 0.92, 0.88, 0.0500, 0.7320,
                             MONITOR_STATUS_FLAGGED, VIOLATION_TYPE_COUNTERFEIT)
    assert_score_4dp(screened["match_score"], match_score(0.92, 0.88, 0.0500), "match_score")


def test_two_decayed_strikes_of_different_weights_total_1886_not_1885(api):
    """PRD §3.3: "Each strike's decayed contribution is rounded half-up to two decimal places **before** any summation."
    PRD §3.3: "Rounding once at the end instead of per strike produces a different, wrong answer, and the difference is observable: one takedown-removal strike and one seizure-confirmed strike both aged 181 days contribute 6.28 (12.55 halved is 6.275, which rounds up) and 12.58 (25.15 halved is 12.575, which rounds up), totalling 18.86 — whereas summing the raw halves first gives 18.85."
    PRD §3.3: "A strike whose age is 180 days or fewer is **fresh** and carries its full base weight; a strike whose age is 181 days or more is **decayed** and carries half its base weight."

    Design: Difficulty/combinatorial_formula/strike_points_round_each_decayed_contribution_before_summation
    """
    ctx = setup_removed_takedown(api, clock="2026-08-17T09:00:00Z")
    ctx["recordation"] = create_recorded_recordation(
        api, ctx["brand"]["id"], ctx["registration"]["id"], "CBP-0001")
    investigation = create_border_seizure_investigation(
        api, ctx["brand"]["id"], ctx["recordation"]["id"],
        seller_id=ctx["seller"]["id"], lot_code="LOT-2026-A")
    submit_investigation_evidence(api, investigation["id"], "EVID-1", "DIST-1")
    conclude_investigation(api, investigation["id"], "DIVERSION_CONFIRMED", "FIND-1")

    fresh = read_seller(api, ctx["seller"]["id"])
    assert_seller_strikes(fresh, 37.70, 37.70, "UNDER_INVESTIGATION")

    # 2027-02-14T09:00:00Z is 181 whole days after both effective instants.
    set_clock(api, "2027-02-14T09:00:00Z")
    sweep = run_sweep(api)
    assert_sweep_counts(sweep, escalated_seller_count=0, blocked_seller_count=0,
                        deescalated_seller_count=1)

    decayed = read_seller(api, ctx["seller"]["id"])
    expected = strike_total([strike_contribution(12.55, 181), strike_contribution(25.15, 181)])
    assert_score_2dp(decayed["standalone_strike_points"], expected, "standalone_strike_points")
    assert_seller_strikes(decayed, 18.86, 18.86, SELLER_STATUS_ACTIVE)


def test_three_decayed_removal_strikes_total_1884_not_1883(api):
    """PRD §3.3: "Likewise three takedown-removal strikes all aged 181 days total 18.84 per-strike-first, not 18.83."
    PRD §3.3: "The contributions are then added together, the sum is rounded half-up to two decimal places, and the result is capped at 100.00."
    PRD §3.3: "A blocked seller that decays below 60.00 but stays at or above 25.00 lands on `UNDER_INVESTIGATION` rather than jumping straight to `ACTIVE`."

    Design: Difficulty/combinatorial_formula/strike_points_round_each_decayed_contribution_before_summation
    """
    ctx = setup_removed_takedown(api, clock="2026-08-17T09:00:00Z")
    ctx = setup_second_removal_on_same_seller(api, ctx, tag="2")
    ctx = setup_second_removal_on_same_seller(api, ctx, tag="3")

    fresh = read_seller(api, ctx["seller"]["id"])
    assert_seller_strikes(fresh, 37.65, 37.65, "UNDER_INVESTIGATION")

    set_clock(api, "2027-02-14T09:00:00Z")
    sweep = run_sweep(api)
    assert_sweep_counts(sweep, deescalated_seller_count=1, blocked_seller_count=0,
                        escalated_seller_count=0)

    decayed = read_seller(api, ctx["seller"]["id"])
    expected = strike_total([strike_contribution(12.55, 181)] * 3)
    assert_score_2dp(decayed["standalone_strike_points"], expected, "standalone_strike_points")
    assert_seller_strikes(decayed, 18.84, 18.84, SELLER_STATUS_ACTIVE)

    replay = run_sweep(api)
    assert_all_sweep_counts_zero(replay)


def test_service_fee_tier_is_selected_from_the_subtotal_not_the_billable_total(api):
    """PRD §3.6: "A `service_fee_rate` is then selected from `subtotal_cents` **alone**, on an inclusive-upper-bound ladder: a subtotal of 5000 cents or less takes a rate of 0.15, a subtotal above that but no more than 20000 cents takes 0.12, a subtotal above that but no more than 50000 cents takes 0.09, and anything above 50000 cents takes 0.06."
    PRD §3.6: "A purchase of 4200 plus 700 shipping plus no lab fee gives a subtotal of 4900, which sits in the first band at 0.15, a fee of 735 and a billable total of 5635 — and although 5635 falls inside the second band, the rate is not revised to 0.12."
    PRD §3.6: "The order lands in status `ORDERED`, its `ordered_at` is stamped from the logical clock, and its `seller_id` is *copied* at creation from the claim's listing rather than supplied, so that the cooling period can be evaluated per seller."

    Design: Difficulty/combinatorial_formula/test_buy_fee_tier_selected_from_subtotal_not_from_billable_total
    """
    ctx = setup_claim(api, clock="2026-08-05T08:00:00Z")

    ordered = validate_success(api.create_test_buy(
        ctx["claim"]["id"], test_buy_payload(4200, 700, 0), headers=ANALYST), 201)

    assert_test_buy_pricing(ordered, 4200, 700, 0)
    assert_cents(ordered["subtotal_cents"], 4900, "subtotal_cents")
    assert_score_2dp(ordered["service_fee_rate"], 0.15, "service_fee_rate")
    assert_cents(ordered["service_fee_cents"], 735, "service_fee_cents")
    assert_cents(ordered["billable_total_cents"], 5635, "billable_total_cents")
    assert ordered["status"] == TEST_BUY_STATUS_ORDERED, (
        f"Expected ORDERED, got {ordered['status']}")
    assert ordered["seller_id"] == ctx["seller"]["id"], (
        f"seller_id must be copied from the claim's listing, got {ordered['seller_id']}")
    assert_instant_equals(ordered["ordered_at"], "2026-08-05T08:00:00Z", "ordered_at")

    brand = read_brand(api, ctx["brand"]["id"])
    assert_cents(brand["enforcement_spend_cents"], 5635, "enforcement_spend_cents")


@pytest.mark.parametrize(
    "purchase_price_cents,shipping_cents,lab_fee_cents,subtotal,rate,fee,billable",
    [
        (5000, 0, 0, 5000, 0.15, 750, 5750),
        (5001, 0, 0, 5001, 0.12, 600, 5601),
        (4200, 700, 2000, 6900, 0.12, 828, 7728),
        (20000, 0, 0, 20000, 0.12, 2400, 22400),
    ],
)
def test_fee_ladder_bands_are_inclusive_at_their_upper_bounds(
        api, purchase_price_cents, shipping_cents, lab_fee_cents, subtotal, rate, fee, billable):
    """PRD §3.6: "A subtotal of exactly 5000 takes the first band inclusively, giving a fee of 750 and a total of 5750, while a subtotal of 5001 takes the second band, giving a fee of 600 and a total of only 5601 — one extra cent of subtotal makes the order 149 cents cheaper overall."
    PRD §3.6: "Adding a 2000-cent lab fee to the same purchase gives a subtotal of 6900, the second band at 0.12, a fee of 828 and a billable total of 7728."
    PRD §3.6: "A subtotal of exactly 20000 takes the second band inclusively, giving a fee of 2400 and a total of 22400."

    Design: Difficulty/combinatorial_formula/test_buy_fee_tier_selected_from_subtotal_not_from_billable_total
    """
    ctx = setup_claim(api, clock="2026-08-05T08:00:00Z")

    ordered = validate_success(api.create_test_buy(
        ctx["claim"]["id"],
        test_buy_payload(purchase_price_cents, shipping_cents, lab_fee_cents),
        headers=ANALYST), 201)

    expected = test_buy_pricing(purchase_price_cents, shipping_cents, lab_fee_cents)
    assert_cents(ordered["subtotal_cents"], subtotal, "subtotal_cents")
    assert_score_2dp(ordered["service_fee_rate"], rate, "service_fee_rate")
    assert_cents(ordered["service_fee_cents"], fee, "service_fee_cents")
    assert_cents(ordered["billable_total_cents"], billable, "billable_total_cents")
    assert expected["billable_total_cents"] == billable, (
        f"Expected billable {billable}, computed {expected['billable_total_cents']}")

    brand = read_brand(api, ctx["brand"]["id"])
    assert_cents(brand["enforcement_spend_cents"], billable, "enforcement_spend_cents")
