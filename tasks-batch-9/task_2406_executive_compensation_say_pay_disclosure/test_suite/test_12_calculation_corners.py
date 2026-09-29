"""Calculation corners of the executive-compensation pipeline.

Every derivation in this service is pinned to an exact evaluation and rounding
order: the peer-group medians and the nearest-rank benchmark deliberately select
different elements, the size-adjustment factor is clamped and rounded before it
multiplies, the payout curve is inclusive at its knots, the weighted vehicle
factor rounds each contribution before summing, outreach coverage dedupes by
investor key, the clawback waterfall only emits a determination for a strictly
positive overpayment, and the two advisor methodologies weight the same program
differently.
"""

from test_helpers import (
    CHAIR_TWO,
    CONSULTANT,
    IR_LEAD,
    analyze_payload,
    api_client,
    assert_money,
    certify_metric,
    create_award,
    create_engagement,
    create_payout_award_payload,
    create_restatement_event,
    create_screen_payload,
    exclude_peer_member,
    hold_engagement,
    read_award,
    read_determinations,
    read_metric,
    read_pay_program,
    read_peer_group_member,
    read_restatement_event,
    restated_metric_result,
    schedule_engagement,
    set_clock,
    setup_pay_program,
    setup_peer_group,
    setup_vested_annual_incentive_award,
    submit_metric_result,
    validate_success,
)
from test_helpers import make_securities_counsel_headers, COUNSEL_ONE


def test_odd_member_count_medians_take_the_middle_while_benchmark_takes_nearest_rank():
    """Three accepted peers: the medians take the true middle element while the
    benchmark uses the nearest-rank position, so the two numbers disagree.

    PRD: "Sort the accepted peers' `revenue_usd` ascending, breaking ties by the
    membership row's `created_at` ascending; where the count is odd,
    `median_revenue_usd` is the middle value rounded half-up to two decimal
    places, and where the count is even it is the mean of the two middle values,
    likewise rounded to two decimal places."

    PRD: "Both variants are then collapsed to a single figure by the same pinned
    percentile method: sort the list ascending (ties keeping the earlier-created
    membership first), take the value at the position given by rounding one half
    of the count *up* to the next whole number, and round that value half-up to
    two decimal places."

    Design: Corner/calculations/odd_member_count_takes_the_true_middle_while_nearest_rank_picks_index_one
    """
    env = setup_peer_group(
        peer_tickers=("BRVO", "CHRL", "DLTA"),
        benchmark_basis="RAW_MEDIAN",
        target_status="DRAFT",
    )
    peer_group_id = env["peer_group"]["id"]

    group = validate_success(api_client.screen_peer_group(peer_group_id, CONSULTANT), 200)

    assert group["status"] == "SCREENED"
    assert group["accepted_member_count"] == 3
    # Revenues 8e9 / 12e9 / 20e9: the middle value, not the 13,333,333,333.33 mean.
    assert_money(group["median_revenue_usd"], 12000000000.00, "median_revenue_usd")
    assert_money(group["median_market_cap_usd"], 30000000000.00, "median_market_cap_usd")
    # |12e9 - 10e9| / 10e9 == 0.20, so the score is (1 - 0.20) * 100.
    assert_money(group["size_fit_score"], 80.00, "size_fit_score")
    # ceil(0.50 * 3) selects the second of 12,000,000 / 18,000,000 / 24,000,000.
    assert_money(
        group["benchmark_target_tdc_raw_usd"], 18000000.00, "benchmark_target_tdc_raw_usd"
    )
    # Adjusted candidates 12,000,000.00 / 14,999,400.00 / 15,000,000.00.
    assert_money(
        group["benchmark_target_tdc_adjusted_usd"],
        14999400.00,
        "benchmark_target_tdc_adjusted_usd",
    )
    assert_money(group["benchmark_target_tdc_usd"], 18000000.00, "benchmark_target_tdc_usd")


def test_excluded_member_is_left_out_of_the_medians_and_the_benchmark():
    """A peer excluded while the group is still drafting contributes nothing to
    the medians, the size-fit score or either benchmark variant.

    PRD: "Only `ACCEPTED` members participate in the computation; excluded
    members never do, no matter when they were excluded."

    Design: Corner/calculations/excluded_members_never_enter_the_medians_or_the_benchmark
    """
    env = setup_peer_group(
        peer_tickers=("BRVO", "CHRL", "DLTA"),
        benchmark_basis="RAW_MEDIAN",
        target_status="DRAFT",
    )
    peer_group_id = env["peer_group"]["id"]
    excluded_member_id = env["members"]["DLTA"]["id"]

    excluded = exclude_peer_member(
        excluded_member_id,
        "Delta is now four times the issuer revenue after its acquisition.",
    )
    assert excluded["status"] == "EXCLUDED"

    group = validate_success(api_client.screen_peer_group(peer_group_id, CONSULTANT), 200)

    assert group["accepted_member_count"] == 2
    # Only BRVO (8e9 / 16e9 / 12,000,000) and CHRL (12e9 / 30e9 / 18,000,000) count.
    assert_money(group["median_revenue_usd"], 10000000000.00, "median_revenue_usd")
    assert_money(group["median_market_cap_usd"], 23000000000.00, "median_market_cap_usd")
    assert_money(group["size_fit_score"], 100.00, "size_fit_score")
    # ceil(0.50 * 2) selects the lower of the two middle values.
    assert_money(
        group["benchmark_target_tdc_raw_usd"], 12000000.00, "benchmark_target_tdc_raw_usd"
    )
    assert_money(
        group["benchmark_target_tdc_adjusted_usd"],
        14999400.00,
        "benchmark_target_tdc_adjusted_usd",
    )

    # The excluded membership survives the screen as a historical row.
    still_there = read_peer_group_member(peer_group_id, excluded_member_id)
    assert still_there is not None, "an excluded membership row is kept, not deleted"
    assert still_there["status"] == "EXCLUDED"


def test_size_adjustment_factor_is_clamped_at_both_declared_bounds():
    """One peer set exercises both clamp bounds: a peer 2.5 times smaller than
    the issuer is scaled by 2.0000 and a peer 2.5 times larger by 0.5000.

    PRD: "The `SIZE_ADJUSTED` variant first scales each peer's disclosed
    compensation for the size difference: divide the issuer's revenue by that
    peer's revenue, clamp the quotient to no less than 0.5 and no more than 2.0,
    round the clamped factor half-up to four decimal places, multiply the peer's
    `ceo_tdc_usd` by that rounded factor, and round the product half-up to two
    decimal places."

    Design: Corner/calculations/the_size_adjustment_factor_is_clamped_at_both_declared_bounds
    """
    env = setup_peer_group(
        peer_tickers=("FOXT", "GOLF"),
        benchmark_basis="SIZE_ADJUSTED",
        target_status="DRAFT",
        inclusion_reason="BUSINESS_MODEL_ANALOG",
    )
    peer_group_id = env["peer_group"]["id"]

    group = validate_success(api_client.screen_peer_group(peer_group_id, CONSULTANT), 200)

    assert group["accepted_member_count"] == 2
    assert_money(group["median_revenue_usd"], 14500000000.00, "median_revenue_usd")
    assert_money(group["median_market_cap_usd"], 29000000000.00, "median_market_cap_usd")
    assert_money(group["size_fit_score"], 55.00, "size_fit_score")
    # Raw candidates 5,000,000.00 and 30,000,000.00; nearest rank takes the lower.
    assert_money(
        group["benchmark_target_tdc_raw_usd"], 5000000.00, "benchmark_target_tdc_raw_usd"
    )
    # FOXT 10e9/4e9 == 2.5 clamps down to 2.0000 -> 10,000,000.00;
    # GOLF 10e9/25e9 == 0.4 clamps up to 0.5000 -> 15,000,000.00.
    # Unclamped the candidates would have been 12,500,000.00 and 12,000,000.00.
    assert_money(
        group["benchmark_target_tdc_adjusted_usd"],
        10000000.00,
        "benchmark_target_tdc_adjusted_usd",
    )
    assert_money(group["benchmark_target_tdc_usd"], 10000000.00, "benchmark_target_tdc_usd")


def test_payout_curve_pays_threshold_at_the_knot_and_zero_one_tick_below():
    """The curve is inclusive at its knots: 4.00 against a 4.00 threshold pays
    50.00, 3.99 pays 0.00 with no downward interpolation, and 6.00 at the
    maximum pays 200.00, so the weighted vehicle factor is 80.00.

    PRD: "The boundaries are inclusive in the earning direction: an achievement
    exactly equal to `threshold_value` pays exactly `threshold_payout_pct`, an
    achievement exactly equal to `maximum_value` pays exactly
    `maximum_payout_pct`, and one unit past the threshold in the failing
    direction pays 0.00."

    PRD: "For an `ANNUAL_INCENTIVE` award the cash follows: the uncapped amount
    is `target_amount_usd` multiplied by `certified_factor_pct` divided by 100,
    rounded to two decimal places; the cap is `target_amount_usd` multiplied by
    the program's `sti_max_multiple`, rounded to two decimal places; and
    `earned_amount_usd` is the lesser of the two, the cap being applied only
    after both figures have been rounded."

    Design: Corner/calculations/the_payout_curve_pays_threshold_at_threshold_and_zero_one_tick_below
    """
    env = setup_pay_program(
        metric_curves=("ADJ_EPS_LINEAR", "REVENUE_GROWTH_STEP", "ADJ_EPS_LINEAR"),
        metric_overrides=[
            {"weight_pct": 40.00},
            {"weight_pct": 30.00, "interpolation": "LINEAR"},
            {"weight_pct": 30.00, "metric_code": "FCF"},
        ],
        approve=True,
    )
    program_id = env["program"]["id"]
    at_threshold, one_tick_below, at_maximum = env["metrics"]

    submit_metric_result(at_threshold["id"], 4.00)
    submit_metric_result(one_tick_below["id"], 3.99)
    submit_metric_result(at_maximum["id"], 6.00)
    for metric in env["metrics"]:
        certify_metric(metric["id"], chair_user_id=CHAIR_TWO)

    at_threshold = read_metric(program_id, at_threshold["id"])
    one_tick_below = read_metric(program_id, one_tick_below["id"])
    at_maximum = read_metric(program_id, at_maximum["id"])

    assert at_threshold["status"] == "CERTIFIED"
    assert one_tick_below["status"] == "CERTIFIED"
    assert at_maximum["status"] == "CERTIFIED"
    assert_money(at_threshold["payout_factor_pct"], 50.00, "payout_factor_pct at threshold")
    assert_money(one_tick_below["payout_factor_pct"], 0.00, "payout_factor_pct below threshold")
    assert_money(at_maximum["payout_factor_pct"], 200.00, "payout_factor_pct at maximum")

    award = validate_success(
        api_client.create_payout_award(
            program_id,
            create_payout_award_payload(env["ceo"]["id"], "ANNUAL_INCENTIVE"),
            CONSULTANT,
        ),
        201,
    )

    # 50.00*40/100 + 0.00*30/100 + 200.00*30/100 == 20.00 + 0.00 + 60.00.
    assert_money(award["certified_factor_pct"], 80.00, "certified_factor_pct")
    assert_money(award["target_amount_usd"], 1800000.00, "target_amount_usd")
    # Uncapped 1,440,000.00 against a 3,600,000.00 cap, so the cap is not binding.
    assert_money(award["earned_amount_usd"], 1440000.00, "earned_amount_usd")


def test_outreach_coverage_counts_the_earliest_row_per_investor_key_only():
    """A second conversation with the same investor adds nothing to coverage:
    the running total keeps one contributor per investor key.

    PRD: "At the first level, the program recomputes `outreach_coverage_pct`:
    gather the program's `HELD` engagements, keep at most one row per distinct
    `investor_key` — the contributor being the row with the **earliest**
    `created_at`, so a second conversation with the same investor adds nothing —
    sum the contributors' `ownership_pct`, cap the sum at 100.00 and round
    half-up to two decimal places."

    Design: Corner/calculations/outreach_coverage_counts_the_earliest_row_per_investor_key_only
    """
    env = setup_pay_program(approve=False)
    program_id = env["program"]["id"]

    first_blackrock = create_engagement(program_id, "BlackRock", 20.00, "MEETING")
    schedule_engagement(
        first_blackrock["id"], "2027-03-01T00:00:00Z", "2027-03-05T00:00:00Z"
    )
    # Adjacency is permitted, so the same investor may hold a second half-open slot.
    second_blackrock = create_engagement(program_id, "BlackRock", 5.00, "MEETING")
    schedule_engagement(
        second_blackrock["id"], "2027-03-05T00:00:00Z", "2027-03-08T00:00:00Z"
    )
    vanguard = create_engagement(program_id, "Vanguard", 11.00, "MEETING")
    schedule_engagement(vanguard["id"], "2027-03-02T00:00:00Z", "2027-03-06T00:00:00Z")

    hold_engagement(first_blackrock["id"], "SUPPORTIVE")
    assert_money(
        read_pay_program(program_id)["outreach_coverage_pct"],
        20.00,
        "outreach_coverage_pct after the first BlackRock conversation",
    )

    duplicate = hold_engagement(second_blackrock["id"], "CONCERNED")
    assert duplicate["engagement_status"] == "HELD"
    assert duplicate["feedback_position"] == "CONCERNED"
    assert_money(
        read_pay_program(program_id)["outreach_coverage_pct"],
        20.00,
        "outreach_coverage_pct after the duplicate investor key",
    )

    hold_engagement(vanguard["id"], "SUPPORTIVE")
    # 20.00 + 11.00, never the naive 36.00 sum of all three ownership stakes.
    assert_money(
        read_pay_program(program_id)["outreach_coverage_pct"],
        31.00,
        "outreach_coverage_pct after Vanguard",
    )


def test_unchanged_restated_achievement_creates_no_clawback_determination():
    """Restating an achievement to its original value leaves the payout factor
    where it was, so the overpayment is zero and no determination row is written.

    PRD: "A determination row is created, in status `CALCULATED`, only for awards
    whose `recoverable_amount_usd` is strictly greater than 0.00; awards yielding
    exactly 0.00 produce no row at all."

    Design: Corner/calculations/an_unchanged_restated_achievement_creates_no_clawback_determination
    """
    env = setup_vested_annual_incentive_award(settlement_date="2026-09-30T00:00:00Z")
    issuer_id = env["issuer"]["id"]
    award_id = env["awards"]["annual_incentive"]["id"]
    adj_eps = env["metrics"][0]

    set_clock("2026-10-01T00:00:00Z")
    event = create_restatement_event(issuer_id)

    restated = validate_success(
        api_client.analyze_restatement_event(
            event["id"],
            analyze_payload([restated_metric_result(adj_eps["id"], 5.50)]),
            make_securities_counsel_headers(COUNSEL_ONE),
        ),
        200,
    )

    assert restated["status"] == "ANALYZED"
    assert restated["determination_count"] == 0
    assert_money(restated["recoverable_total_usd"], 0.00, "recoverable_total_usd")

    stored_event = read_restatement_event(issuer_id, event["id"])
    assert stored_event["status"] == "ANALYZED"
    assert stored_event["determination_count"] == 0

    assert read_determinations(restatement_event_id=event["id"]) == [], (
        "no determination row exists when the restated amount equals the realized amount"
    )

    # The audit trail keeps both readings of the metric's factor.
    metric = read_metric(env["program"]["id"], adj_eps["id"])
    assert metric["status"] == "RESTATED"
    assert_money(metric["payout_factor_pct"], 150.00, "payout_factor_pct")
    assert_money(metric["restated_payout_factor_pct"], 150.00, "restated_payout_factor_pct")

    award = read_award(award_id)
    assert award["status"] == "VESTED", "an award with nothing to recover is untouched"
    assert_money(award["realized_value_usd"], 2340000.00, "realized_value_usd")


def test_the_two_advisor_weightings_land_one_program_in_different_concern_bands():
    """Identical program inputs score 21.70 under ISS and 32.85 under Glass
    Lewis, straddling the 30.00 band edge.

    PRD: "Under `ISS`, engagement is ignored entirely: `outreach_component` is
    null, and `concern_score` is 0.50 of the alignment component plus 0.30 of the
    mix component plus 0.20 of the rigor component, rounded to two decimal places
    — an issuer that has done no shareholder outreach at all is not penalised."

    PRD: "The score is banded into `concern_level`: `LOW` below 30.00, `MEDIUM`
    at or above 30.00 but below 60.00, and `HIGH` at or above 60.00 — exactly
    30.00 is `MEDIUM` and exactly 60.00 is `HIGH`."

    Design: Corner/calculations/the_two_advisor_weightings_land_one_program_in_different_concern_bands
    """
    env = setup_pay_program(approve=False)
    program_id = env["program"]["id"]

    create_award(
        program_id,
        env["ceo"]["id"],
        "LONG_TERM_PSU",
        units_granted=100000,
        grant_price_usd=50.00,
    )

    program = read_pay_program(program_id)
    assert_money(program["performance_based_pct"], 61.00, "performance_based_pct")
    assert_money(program["degree_of_alignment"], 30.00, "degree_of_alignment")
    assert_money(program["outreach_coverage_pct"], 0.00, "outreach_coverage_pct")
    assert program["alignment_status"] == "ALIGNED"

    iss = validate_success(
        api_client.create_proxy_advisor_screen(
            program_id, create_screen_payload("ISS"), IR_LEAD
        ),
        201,
    )
    glass_lewis = validate_success(
        api_client.create_proxy_advisor_screen(
            program_id, create_screen_payload("GLASS_LEWIS"), IR_LEAD
        ),
        201,
    )

    # Alignment component 50.00 - 30.00 == 20.00; mix component 100.00 - 61.00 == 39.00;
    # rigor component 0.00 because no goal was ever adjusted.
    assert_money(iss["alignment_component"], 20.00, "ISS alignment_component")
    assert_money(iss["mix_component"], 39.00, "ISS mix_component")
    assert_money(iss["rigor_component"], 0.00, "ISS rigor_component")
    assert iss["outreach_component"] is None, "ISS ignores engagement entirely"
    # 0.50*20.00 + 0.30*39.00 + 0.20*0.00
    assert_money(iss["concern_score"], 21.70, "ISS concern_score")
    assert iss["concern_level"] == "LOW"
    assert iss["recommendation"] == "FOR"
    assert iss["status"] == "SCREENED"

    # 0.35*20.00 + 0.15*39.00 + 0.30*0.00 + 0.20*100.00
    assert_money(glass_lewis["outreach_component"], 100.00, "GLASS_LEWIS outreach_component")
    assert_money(glass_lewis["concern_score"], 32.85, "GLASS_LEWIS concern_score")
    assert glass_lewis["concern_level"] == "MEDIUM"
    assert glass_lewis["recommendation"] == "FOR"
    assert glass_lewis["status"] == "SCREENED"

    assert glass_lewis["concern_score"] > iss["concern_score"], (
        "the same program data yields a higher Glass Lewis score"
    )
