"""The order in which rounding, aggregation, tier lookup and capping happen
inside the premium build-up."""

from test_helpers import (
    ADMIN,
    add_scheduled_item,
    bootstrap_zone,
    get_success_data,
    open_account,
    open_policy,
    open_pool,
    rate_policy_ok,
    read_policy,
    reservation_by_peril,
    setup_full_schedule_policy,
    setup_thin_hail_zone_policy,
)


def test_five_property_lines_are_each_rounded_before_they_are_added(api):
    """"Property premium and livestock premium both round each line first and
    then add the already-rounded integers; summing the unrounded products and
    rounding once at the end produces a different — and incorrect — total, and
    the difference is observable." On this schedule the five lines are 144000,
    30888, 89427, 59450 and 100602, so the contract order gives 424367 while
    rounding the summed products once gives 424366.

    Design: Difficulty/combinatorial_formula/property_premium_per_line_rounding_then_sum
    """
    scenario = setup_full_schedule_policy()

    rated = rate_policy_ok(scenario.policy_id)

    assert rated["property_premium_cents"] == 424_367
    assert rated["property_premium_cents"] != 424_366, (
        "summing the unrounded products and rounding once at the end is one cent low"
    )

    items = get_success_data(
        api.list_scheduled_items(scenario.policy_id, ADMIN, params={"limit": 100})
    )
    insured = [row["insured_value_cents"] for row in items]
    assert insured == [40_000_000, 5_280_000, 11_040_368, 6_005_000, 8_280_000]

    stored_crop = next(row for row in items if row["item_class"] == "STORED_CROP")
    assert stored_crop["insured_value_cents"] == 6_005_000, (
        "a season running 10..2 does not include the rating month 8"
    )


def test_full_package_rollup_adds_already_rounded_component_totals(api):
    """"Conversely, sums that add values which were already rounded when their
    own row was written (liability premium, exposed total insured value, the
    base and grand totals) are exact integer additions with no further
    rounding." Property 424367 plus livestock 286875 plus liability 402500 is
    exactly 1113742, and adding the 300810 catastrophe load gives 1414552.

    Design: Difficulty/combinatorial_formula/property_premium_per_line_rounding_then_sum
    """
    scenario = setup_full_schedule_policy()

    rated = rate_policy_ok(scenario.policy_id)

    assert rated["livestock_premium_cents"] == 286_875
    assert rated["liability_premium_cents"] == 402_500
    assert rated["base_premium_cents"] == 1_113_742
    assert rated["exposed_tiv_cents"] == 96_105_368
    assert rated["cat_load_cents"] == 300_810
    assert rated["total_premium_cents"] == 1_414_552
    assert rated["uw_status"] == "RATED", (
        "96105368 does not exceed 250000000, 800 visitors do not exceed 2000, "
        "no utilization exceeds 0.90 and no inspection has completed"
    )


def test_scarcity_tier_is_selected_from_the_unrounded_utilization_ratio(api):
    """"The prospective utilization is the pool's `reserved_cents` plus its
    `committed_cents` plus this new `amount_cents`, all divided by the pool's
    `total_capacity_cents`, evaluated as an exact ratio and never rounded before
    it is used." Against a HAIL pool of 39999999 cents the exact ratio
    0.5000000125 sits above the 0.50 edge and selects 1.15, even though the
    figure stored on the reservation rounds to 0.500000.

    Design: Difficulty/combinatorial_formula/cat_load_unrounded_utilization_tier_then_scarcity
    """
    scenario = setup_thin_hail_zone_policy("ZN-3", 39_999_999)

    rate_policy_ok(scenario.policy_id)
    reservations = reservation_by_peril(scenario.policy_id)

    hail = reservations["HAIL"]
    assert hail["amount_cents"] == 20_000_000
    assert float(hail["utilization_at_rating"]) == 0.500000
    assert float(hail["scarcity_factor"]) == 1.15, (
        "the tier comes from the unrounded ratio, not from the stored six-decimal figure"
    )
    assert hail["load_cents"] == 73_600
    assert hail["load_cents"] != 64_000


def test_catastrophe_load_multiplies_the_rated_amount_by_the_scarcity_factor(api):
    """"`load_cents` is `amount_cents` multiplied by the catastrophe rate for
    the peril — 0.0032 for `HAIL`, 0.0021 for `WIND`, 0.0045 for `WILDFIRE` —
    multiplied by `scarcity_factor`, rounded half up." Only the thin HAIL pool
    is scarce, so WIND holds 25200 and WILDFIRE 36000 at factor 1.00 while HAIL
    carries 73600, giving 134800 in total.

    Design: Difficulty/combinatorial_formula/cat_load_unrounded_utilization_tier_then_scarcity
    """
    scenario = setup_thin_hail_zone_policy("ZN-3", 39_999_999)

    rated = rate_policy_ok(scenario.policy_id)
    reservations = reservation_by_peril(scenario.policy_id)

    assert float(reservations["WIND"]["scarcity_factor"]) == 1.00
    assert reservations["WIND"]["load_cents"] == 25_200
    assert float(reservations["WILDFIRE"]["scarcity_factor"]) == 1.00
    assert reservations["WILDFIRE"]["load_cents"] == 36_000
    assert rated["cat_load_cents"] == 134_800
    assert rated["property_premium_cents"] == 144_000
    assert rated["total_premium_cents"] == 278_800


def test_salvage_floor_is_applied_before_the_class_cap(api):
    """"The insured value is then the larger of the depreciated value and the
    salvage floor, capped at the class cap, rounded half up. The floor is
    applied before the cap; reversing those two would let a floored value escape
    its class cap." A sprayer fleet stated at 300000000 depreciates to 54000000,
    floors at 60000000 and must still be capped to the 40000000 equipment cap.

    Design: Difficulty/combinatorial_formula/acv_salvage_floor_nested_inside_class_cap
    """
    scenario = bootstrap_zone()

    row = add_scheduled_item(
        scenario.agent_headers,
        scenario.policy_id,
        item_class="EQUIPMENT",
        description="Self-propelled sprayer fleet",
        valuation_basis="ACV",
        stated_value_cents=300_000_000,
        age_years=12,
        condition_grade="D",
    )

    assert row["insured_value_cents"] == 40_000_000
    assert row["insured_value_cents"] != 60_000_000, (
        "capping before flooring would let the salvage floor escape the class cap"
    )
    assert row["insured_value_cents"] != 54_000_000, (
        "the depreciated value alone ignores the salvage floor"
    )


def test_depreciation_fraction_is_capped_at_sixty_percent(api):
    """"First the depreciation fraction: the per-year depreciation rate for the
    item's class multiplied by `age_years`, but never allowed to exceed 0.60."
    Twelve years of equipment at 0.070 a year would reach 0.84, so the capped
    0.60 fraction and the grade-D condition factor together fix the insured
    value at the 40000000 class cap and the property line at 324000.

    Design: Difficulty/combinatorial_formula/acv_salvage_floor_nested_inside_class_cap
    """
    scenario = bootstrap_zone()
    add_scheduled_item(
        scenario.agent_headers,
        scenario.policy_id,
        item_class="EQUIPMENT",
        description="Self-propelled sprayer fleet",
        valuation_basis="ACV",
        stated_value_cents=300_000_000,
        age_years=12,
        condition_grade="D",
    )

    rated = rate_policy_ok(scenario.policy_id)

    assert rated["exposed_tiv_cents"] == 40_000_000
    assert rated["property_premium_cents"] == 324_000
    assert rated["cat_load_cents"] == 125_200
    assert rated["total_premium_cents"] == 449_200
    assert read_policy(scenario.policy_id)["total_premium_cents"] == 449_200


def test_a_second_zone_is_rated_independently_of_the_first(api):
    """"Because pools are per-peril, the growth on one pool is visible only to
    its own peril and the three amounts are independent of one another." A
    policy in a second zone draws on that zone's own pools, so its HAIL
    utilization is computed against the second pool's capacity alone.

    Design: Difficulty/combinatorial_formula/cat_load_unrounded_utilization_tier_then_scarcity
    """
    scenario = setup_thin_hail_zone_policy("ZN-3", 39_999_999)
    rate_policy_ok(scenario.policy_id)

    open_pool("ZN-9", "HAIL", total_capacity_cents=200_000_000)
    open_pool("ZN-9", "WIND", total_capacity_cents=200_000_000)
    open_pool("ZN-9", "WILDFIRE", total_capacity_cents=200_000_000)
    other_account = open_account(
        scenario.agent_headers, legal_name="Far Field Farms", cat_zone_code="ZN-9"
    )
    other_policy = open_policy(scenario.agent_headers, other_account["id"])
    add_scheduled_item(scenario.agent_headers, other_policy["id"])

    rated = rate_policy_ok(other_policy["id"])
    reservations = reservation_by_peril(other_policy["id"])

    assert float(reservations["HAIL"]["utilization_at_rating"]) == 0.100000
    assert float(reservations["HAIL"]["scarcity_factor"]) == 1.00
    assert reservations["HAIL"]["load_cents"] == 64_000
    assert rated["cat_load_cents"] == 125_200
    assert rated["total_premium_cents"] == 269_200
