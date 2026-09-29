"""The library-versus-custom sourcing comparison."""
from test_helpers import (
    ApiErrorId,
    create_library_track,
    make_producer_headers,
    set_clock,
    setup_engagement_in_demo,
    setup_engagement_in_production,
    setup_license_deal,
    validate_error,
    validate_success,
)


def test_sourcing_comparison_picks_the_cheapest_eligible_track(api):
    """PRD §3.9: "The custom side is the engagement's `spent_cents` plus its
    `committed_cents` plus the `license_fee_quoted_cents` of its live licence deal,
    where the live deal is the one whose status is `DRAFT`, `PROPOSED`, `ACCEPTED`,
    `ACTIVE` or `RENEWAL_DUE`, ranked by `created_at` descending with `version`
    descending as tie-break, taking the first row; when the engagement has no such deal
    the quote contribution is zero."
    PRD §3.9: "The library side starts with an eligibility filter: a track qualifies
    only if its `status` is `ACTIVE`, its `max_markets` is at least the brief's market
    count, and its `min_length_seconds` is no greater than the brief's shortest cut."
    PRD §3.9: "Each qualifying track is quoted as its `blanket_fee_cents` plus its
    `per_market_fee_cents` multiplied by the brief's market count, and the cheapest
    quote wins with `created_at` ascending as tie-break; the winner's identifier is
    reported as `selected_library_track_id`."
    PRD §3.9: "Finally, `recommended_mode` is `LIBRARY` when `library_total_cents`
    multiplied by 100 is less than or equal to `custom_total_cents` multiplied by 85 —
    that is, when the library comes in at least 15 percent under the custom route — and
    `CUSTOM` in every other case; the comparison is done by integer cross-multiplication,
    never by division."

    Design: Corner/calculations/corner_sourcing_comparison_selects_cheapest_eligible_and_recommends_library
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(
        budget_cents=4_000_000, target_markets=["US_NATIONAL", "US_REGIONAL"],
        required_lengths=[60, 30, 15], demo_fee_cents=150_000, submitted_length_seconds=60)
    setup_license_deal(env, stage="PROPOSED", license_structure="TERM", term_months=12,
                       market_codes=["US_NATIONAL"], creative_fee_cents=800_000)
    cheapest = create_library_track(title="Amber Lift", blanket_fee_cents=200_000,
                                    per_market_fee_cents=30_000, max_markets=3,
                                    min_length_seconds=15)
    create_library_track(title="Copper Run", blanket_fee_cents=120_000,
                         per_market_fee_cents=90_000, max_markets=2, min_length_seconds=15)
    create_library_track(title="Tin Whistle", blanket_fee_cents=50_000,
                         per_market_fee_cents=10_000, max_markets=1, min_length_seconds=30)

    comparison = validate_success(api.get_sourcing_comparison(
        env["project"]["id"], make_producer_headers()))
    assert comparison["custom_total_cents"] == 945_000, (
        "150000 spent plus 0 committed plus the 795000 quote is 945000; "
        f"got {comparison['custom_total_cents']}")
    assert comparison["eligible_track_count"] == 2, (
        "The single-market track is filtered out; "
        f"got {comparison['eligible_track_count']}")
    assert comparison["library_total_cents"] == 260_000, (
        f"200000 + 30000 * 2 = 260000 wins; got {comparison['library_total_cents']}")
    assert comparison["selected_library_track_id"] == cheapest["id"], (
        f"Expected the cheapest track, got {comparison['selected_library_track_id']}")
    assert comparison["savings_cents"] == 685_000, (
        f"945000 - 260000 = 685000; got {comparison['savings_cents']}")
    assert comparison["recommended_mode"] == "LIBRARY", (
        f"260000 * 100 <= 945000 * 85, so LIBRARY; got {comparison['recommended_mode']}")


def test_sourcing_comparison_with_an_empty_eligible_pool_is_rejected(api):
    """PRD §3.9: "The library side starts with an eligibility filter: a track qualifies
    only if its `status` is `ACTIVE`, its `max_markets` is at least the brief's market
    count, and its `min_length_seconds` is no greater than the brief's shortest cut."
    PRD §3.9: "If no track qualifies, the whole read fails with
    `ERR_NO_ELIGIBLE_LIBRARY_TRACK`; otherwise the number that qualified is reported as
    `eligible_track_count`."

    Design: Corner/calculations/corner_sourcing_comparison_with_empty_eligible_pool_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_demo(
        budget_cents=4_000_000, target_markets=["US_NATIONAL", "US_REGIONAL"],
        required_lengths=[60, 30, 15])
    create_library_track(title="Tin Whistle", blanket_fee_cents=50_000,
                         per_market_fee_cents=10_000, max_markets=1, min_length_seconds=15)

    validate_error(
        api.get_sourcing_comparison(env["project"]["id"], make_producer_headers()),
        ApiErrorId.ERR_NO_ELIGIBLE_LIBRARY_TRACK.value, 409)


def test_library_floor_lifts_a_cheap_quote_to_the_minimum(api):
    """PRD §3.9: "`library_total_cents` is the winning quote, raised to a floor of
    25,000 cents if it falls below that."
    PRD §3.9: "`savings_cents` is `custom_total_cents` less `library_total_cents`, and
    may be negative."
    PRD §3.9: "Two inputs come from the engagement's single `APPROVED` brief — the
    number of markets in its `target_markets`, and the shortest cut in its
    `required_lengths`."

    Design: Corner/calculations/corner_library_floor_lifts_a_ten_thousand_cent_quote_to_the_minimum
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(
        budget_cents=4_000_000, target_markets=["US_NATIONAL", "US_REGIONAL"],
        required_lengths=[60, 30, 15], demo_fee_cents=150_000, submitted_length_seconds=60)
    track = create_library_track(title="Penny Loop", blanket_fee_cents=0,
                                 per_market_fee_cents=5_000, max_markets=3,
                                 min_length_seconds=15)

    comparison = validate_success(api.get_sourcing_comparison(
        env["project"]["id"], make_producer_headers()))
    assert comparison["custom_total_cents"] == 150_000, (
        "With no licence deal the quote contribution is zero, leaving the 150000 spent; "
        f"got {comparison['custom_total_cents']}")
    assert comparison["library_total_cents"] == 25_000, (
        f"The 10000-cent quote is lifted to the 25000 floor; "
        f"got {comparison['library_total_cents']}")
    assert comparison["selected_library_track_id"] == track["id"]
    assert comparison["eligible_track_count"] == 1
    assert comparison["savings_cents"] == 125_000, (
        f"150000 - 25000 = 125000; got {comparison['savings_cents']}")
    assert comparison["recommended_mode"] == "LIBRARY", (
        f"25000 * 100 <= 150000 * 85, so LIBRARY; got {comparison['recommended_mode']}")


def test_sourcing_comparison_tie_break_prefers_the_earlier_track(api):
    """PRD §3.9: "Each qualifying track is quoted as its `blanket_fee_cents` plus its
    `per_market_fee_cents` multiplied by the brief's market count, and the cheapest
    quote wins with `created_at` ascending as tie-break; the winner's identifier is
    reported as `selected_library_track_id`."
    PRD §3.9: "Finally, `recommended_mode` is `LIBRARY` when `library_total_cents`
    multiplied by 100 is less than or equal to `custom_total_cents` multiplied by 85 —
    that is, when the library comes in at least 15 percent under the custom route — and
    `CUSTOM` in every other case; the comparison is done by integer cross-multiplication,
    never by division."

    Design: Corner/calculations/corner_sourcing_comparison_tie_break_prefers_the_earlier_created_track
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(
        budget_cents=4_000_000, target_markets=["US_NATIONAL", "US_REGIONAL"],
        required_lengths=[60, 30, 15], demo_fee_cents=150_000, submitted_length_seconds=60)
    earlier = create_library_track(title="Track X", blanket_fee_cents=200_000,
                                   per_market_fee_cents=30_000, max_markets=3,
                                   min_length_seconds=15)
    later = create_library_track(title="Track Y", blanket_fee_cents=260_000,
                                 per_market_fee_cents=0, max_markets=3,
                                 min_length_seconds=15)

    comparison = validate_success(api.get_sourcing_comparison(
        env["project"]["id"], make_producer_headers()))
    assert comparison["library_total_cents"] == 260_000, (
        f"Both tracks quote 260000; got {comparison['library_total_cents']}")
    assert comparison["selected_library_track_id"] == earlier["id"], (
        f"The created_at tie-break must pick the first track; "
        f"got {comparison['selected_library_track_id']}")
    assert comparison["selected_library_track_id"] != later["id"]
    assert comparison["eligible_track_count"] == 2
    assert comparison["custom_total_cents"] == 150_000
    assert comparison["recommended_mode"] == "CUSTOM", (
        f"260000 * 100 exceeds 150000 * 85, so CUSTOM; got {comparison['recommended_mode']}")
