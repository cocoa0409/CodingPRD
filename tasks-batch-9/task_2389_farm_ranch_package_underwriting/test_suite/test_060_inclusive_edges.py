"""Values landing exactly on a declared edge: the scarcity band, the
workers-compensation threshold and a wrap-around seasonal window."""

from test_helpers import (
    add_seasonal_item,
    assert_labor_units_two_decimals,
    assert_utilization_six_decimals,
    bootstrap_zone,
    patch_item_ok,
    rate_policy_ok,
    read_item,
    read_policy,
    reservation_by_peril,
    set_clock,
    setup_thin_hail_zone_policy,
    upsert_labor_profile,
)

WRAPAROUND_TRIO = {
    "peak_season_value_cents": 18_000_000,
    "peak_season_start_month": 10,
    "peak_season_end_month": 2,
}


def test_a_utilization_of_exactly_one_half_stays_in_the_base_scarcity_band(api):
    """"`scarcity_factor` is selected from that ratio in four bands: at most 0.50
    gives 1.00, above 0.50 and at most 0.75 gives 1.15, above 0.75 and at most
    0.90 gives 1.35, above 0.90 and at most 1.00 gives 1.60." A HAIL pool of
    40000000 cents taking a 20000000-cent reservation sits exactly on 0.50, and
    the first band is inclusive on its upper edge, so the factor is 1.00 and the
    load is the unscaled 64000.

    Design: Difficulty/boundary_precision_check/cat_utilization_exactly_half_holds_base_scarcity_tier
    """
    scenario = setup_thin_hail_zone_policy("ZN-E", 40_000_000)

    rated = rate_policy_ok(scenario.policy_id)
    hail = reservation_by_peril(scenario.policy_id)["HAIL"]

    assert hail["amount_cents"] == 20_000_000
    assert_utilization_six_decimals(hail["utilization_at_rating"])
    assert float(hail["utilization_at_rating"]) == 0.500000
    assert float(hail["scarcity_factor"]) == 1.00
    assert hail["load_cents"] == 64_000
    assert rated["cat_load_cents"] == 125_200
    assert rated["total_premium_cents"] == 269_200
    assert rated["uw_status"] == "RATED", (
        "0.50 is not strictly greater than 0.90, so the utilization trigger stays quiet"
    )


def test_one_cent_of_extra_utilization_costs_the_package_9600_cents(api):
    """"The prospective utilization is the pool's `reserved_cents` plus its
    `committed_cents` plus this new `amount_cents`, all divided by the pool's
    `total_capacity_cents`, evaluated as an exact ratio and never rounded before
    it is used." Shrinking the pool by a single cent to 39999999 pushes the ratio
    just past 0.50 into the 1.15 band, so the identical package costs 278800
    rather than 269200 — a difference of exactly 9600 cents.

    Design: Difficulty/boundary_precision_check/cat_utilization_exactly_half_holds_base_scarcity_tier
    """
    on_the_edge = setup_thin_hail_zone_policy("ZN-E", 40_000_000)
    just_over = setup_thin_hail_zone_policy("ZN-F", 39_999_999)

    edge_rated = rate_policy_ok(on_the_edge.policy_id)
    over_rated = rate_policy_ok(just_over.policy_id)

    edge_hail = reservation_by_peril(on_the_edge.policy_id)["HAIL"]
    over_hail = reservation_by_peril(just_over.policy_id)["HAIL"]

    assert float(edge_hail["scarcity_factor"]) == 1.00
    assert float(over_hail["scarcity_factor"]) == 1.15
    assert edge_hail["load_cents"] == 64_000
    assert over_hail["load_cents"] == 73_600

    assert edge_rated["cat_load_cents"] == 125_200
    assert over_rated["cat_load_cents"] == 134_800
    assert edge_rated["total_premium_cents"] == 269_200
    assert over_rated["total_premium_cents"] == 278_800
    assert over_rated["total_premium_cents"] - edge_rated["total_premium_cents"] == 9_600


def test_five_exposure_units_do_not_require_workers_compensation(api):
    """"`wc_required` is true exactly when `labor_exposure_units` is at least
    6.00 — the threshold is inclusive, so a crew of four year-round and four
    seasonal workers lands precisely on 6.00 and does require coverage, while
    three year-round and four seasonal workers reach only 5.00 and do not."
    Three full-time plus four seasonal is 3.00 plus 2.00, so the profile stays
    `NOT_REQUIRED` and needs no proof at all.

    Design: Difficulty/boundary_precision_check/labor_exposure_units_exactly_six_requires_wc
    """
    scenario = bootstrap_zone()

    profile = upsert_labor_profile(
        scenario.agent_headers,
        scenario.policy_id,
        full_time_count=3,
        seasonal_count=4,
        migrant_h2a_count=0,
    )

    assert_labor_units_two_decimals(profile["labor_exposure_units"])
    assert float(profile["labor_exposure_units"]) == 5.00
    assert profile["wc_required"] is False
    assert profile["coordination_status"] == "NOT_REQUIRED"
    assert profile["version"] == 1


def test_exactly_six_exposure_units_require_workers_compensation(api):
    """"From the three headcounts the system derives `labor_exposure_units`:
    `full_time_count` weighted at 1.00, plus `seasonal_count` weighted at 0.50,
    plus `migrant_h2a_count` weighted at 0.75, with the sum rounded half up to
    exactly two decimal places." One extra year-round hand takes the crew from
    5.00 to precisely 6.00 on the inclusive threshold, flipping `wc_required`
    and reopening the coordination cycle at `PENDING_PROOF` on the same row.

    Design: Difficulty/boundary_precision_check/labor_exposure_units_exactly_six_requires_wc
    """
    scenario = bootstrap_zone()
    below = upsert_labor_profile(
        scenario.agent_headers,
        scenario.policy_id,
        full_time_count=3,
        seasonal_count=4,
        migrant_h2a_count=0,
    )

    at_threshold = upsert_labor_profile(
        scenario.agent_headers,
        scenario.policy_id,
        full_time_count=4,
        seasonal_count=4,
        migrant_h2a_count=0,
    )

    assert at_threshold["id"] == below["id"]
    assert_labor_units_two_decimals(at_threshold["labor_exposure_units"])
    assert float(at_threshold["labor_exposure_units"]) == 6.00
    assert at_threshold["wc_required"] is True
    assert at_threshold["coordination_status"] == "PENDING_PROOF"
    assert at_threshold["version"] == 2


def test_february_falls_inside_a_season_that_wraps_the_turn_of_the_year(api):
    """"When `peak_season_start_month` is greater than `peak_season_end_month`
    the window wraps across the turn of the year, and the item is in peak when
    the valuation month is at or after the start month *or* at or before the end
    month — a window running from October through February therefore includes
    December, January and February." Valued at the last second of February the
    stored crop carries its 18000000-cent peak value, not its 6005000-cent
    off-peak value.

    Design: Difficulty/boundary_precision_check/stored_crop_wraparound_season_february_boundary
    """
    scenario = bootstrap_zone(clock="2026-02-28T23:59:59Z")

    row = add_seasonal_item(
        scenario.agent_headers,
        scenario.policy_id,
        item_class="STORED_CROP",
        stated_value_cents=6_005_000,
        **WRAPAROUND_TRIO,
    )

    assert row["insured_value_cents"] == 18_000_000
    assert row["valued_at"].startswith("2026-02-28T23:59:59")
    assert row["stated_value_cents"] == 6_005_000
    assert row["peak_season_value_cents"] == 18_000_000
    assert row["version"] == 1


def test_the_first_of_march_falls_outside_the_same_wrapped_window(api):
    """"Every such amendment re-derives the item's insured value, restamps
    `valued_at`, and lifts the item's `version` by 1." Re-submitting the very
    same seasonal trio one second past the end of February drops the insured
    value back to the 6005000-cent off-peak figure, because the valuation month
    is the current clock month and March is neither at or after October nor at or
    before February.

    Design: Difficulty/boundary_precision_check/stored_crop_wraparound_season_february_boundary
    """
    scenario = bootstrap_zone(clock="2026-02-28T23:59:59Z")
    row = add_seasonal_item(
        scenario.agent_headers,
        scenario.policy_id,
        item_class="STORED_CROP",
        stated_value_cents=6_005_000,
        **WRAPAROUND_TRIO,
    )
    assert row["insured_value_cents"] == 18_000_000

    set_clock("2026-03-01T00:00:00Z")
    amended = patch_item_ok(
        row["id"],
        scenario.agent_headers,
        stated_value_cents=6_005_000,
        **WRAPAROUND_TRIO,
    )

    assert amended["insured_value_cents"] == 6_005_000
    assert amended["valued_at"].startswith("2026-03-01T00:00:00")
    assert amended["version"] == 2
    assert amended["peak_season_value_cents"] == 18_000_000
    assert amended["peak_season_start_month"] == 10
    assert amended["peak_season_end_month"] == 2

    assert read_item(row["id"])["insured_value_cents"] == 6_005_000
    assert read_policy(scenario.policy_id)["uw_status"] == "DRAFT", (
        "amending an item on a DRAFT policy simply stores it"
    )
