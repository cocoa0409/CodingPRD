"""Formulas whose answer depends on the order their steps run in.

Three shapes appear here. A per-segment rounding that must happen before the sum
rather than after it, worth exactly one cent. A surcharge tier keyed on the
figure that exists before the surcharge is added rather than on the total that
results, worth twenty-five dollars. And an inventory target built from a step
function, a capped damper and a clamp that is applied before the final rounding,
where the same three inputs land inside the band, on the ceiling or on the floor.
"""

from test_helpers import (
    BILLING,
    CLERK,
    ENGINEER,
    advance_lot_to_tested,
    assert_four_decimal_price,
    assert_money,
    create_lot,
    create_metal_quote,
    create_order,
    create_reel,
    create_released_product,
    create_shipment_payload,
    current_order_version,
    get_success_data,
    load_reel_payload,
    read_product,
    release_lot,
    setup_baseline,
    setup_lv_catalog,
    validate_success,
)

CUT_ORDER = {
    "order_number": "SO-CUT",
    "ordered_kft": 3.750,
    "cut_to_length_service": True,
    "requested_cut_lengths_ft": [1250, 1250, 1250],
}
# Six copper settlements: range 0.90 over a mean of 4.2916666..., so the index
# rounds to 0.2097.
VOLATILE_COPPER_SERIES = (
    ("2026-08-01", 4.00),
    ("2026-08-02", 4.05),
    ("2026-08-03", 4.10),
    ("2026-08-04", 4.60),
    ("2026-08-05", 4.90),
)
# Exactly the three-quote minimum, range 4.00 over a mean of 4.00, so the index
# is 1.0000 and the damper saturates at its cap.
SATURATING_COPPER_SERIES = (
    ("2026-08-01", 2.00),
    ("2026-08-02", 4.00),
    ("2026-08-03", 6.00),
)
ALUMINUM_SKU = {
    "product_code": "XHHW-4/0-AL",
    "awg_size": "4/0",
    "conductor_metal": "ALUMINUM",
    "conductor_construction": "COMPRESSED_37",
    "application_rating": "XHHW_2",
    "insulation_thickness_mils": 45.0,
    "conductor_lbs_per_kft": 66.0,
    "base_target_kft": 100.0,
}


def _post_series(api, series, metal="COPPER", source="COMEX"):
    for effective_date, price in series:
        create_metal_quote(
            api, metal=metal, effective_date=effective_date,
            settlement_price_usd_per_lb=price, source=source,
        )


def test_three_equal_cuts_are_rounded_per_segment_before_they_are_summed(api):
    """Three 1250 ft segments at 106.7800 per kft round to 133.48 each and sum to
    400.44. Summing the exact segment amounts and rounding once would answer
    400.43, one cent lower.

    PRD 3.5: "For a cut-to-length order, `quoted_subtotal_usd` is the sum, taken
    over `requested_cut_lengths_ft` in list order, of each segment's own amount —
    the segment's length in feet divided by 1000, multiplied by
    `quoted_unit_price_usd_per_kft`, and rounded half up to two decimals *before*
    it enters the sum."

    PRD 3.5: "`quoted_cut_fee_usd` for such an order is a flat twelve dollars fifty
    per cut multiplied by the number of entries in `requested_cut_lengths_ft`,
    rounded half up to two decimals."

    PRD 3.5: "**Step five totals the quote:** `quoted_total_usd` is
    `quoted_subtotal_usd` plus `quoted_cut_fee_usd` plus `quoted_surcharge_usd`,
    rounded half up to two decimals."

    Design: Difficulty/combinatorial_formula/cut_to_length_per_segment_rounding_order_mode_b
    """
    world = setup_baseline(api, order_overrides=CUT_ORDER)
    order = world["order"]

    assert_four_decimal_price(
        order["quoted_unit_price_usd_per_kft"], 106.7800, "85.00 plus 19.8 x 1.10"
    )
    assert_money(
        order["quoted_subtotal_usd"], 400.44,
        "three segment amounts of 133.48, each rounded before it entered the sum",
    )
    assert order["quoted_subtotal_usd"] != 400.43, (
        "400.43 is what rounding the exact 400.425 once at the end would produce"
    )
    assert_money(order["quoted_cut_fee_usd"], 37.50, "12.50 for each of three cuts")
    assert_money(order["quoted_surcharge_usd"], 8.01, "two percent of 400.44")
    assert_money(order["quoted_total_usd"], 445.95, "subtotal, cut fee and surcharge")


def test_the_invoice_repeats_the_per_segment_rounding_over_the_shipped_cuts(api):
    """The invoice re-derives the same figure from `cuts_count` rather than copying
    the quote, and lands on the same 400.44.

    PRD 3.9: "When the order is a cut-to-length order, `extended_amount_usd` is the
    sum, taken over the *first* `cuts_count` entries of the order's
    `requested_cut_lengths_ft` in list order, of each segment's own amount — the
    segment's length in feet divided by 1000, multiplied by
    `unit_price_usd_per_kft`, and rounded half up to two decimals before it enters
    the sum — and `cut_fee_usd` is twelve dollars fifty per cut multiplied by
    `cuts_count`, rounded half up to two decimals."

    PRD 3.9: "The volatility surcharge tier is then keyed on `extended_amount_usd`
    alone, exactly as the quote's tier was keyed on its subtotal alone: two percent
    when the extension is below five thousand dollars, one and a half percent when
    it is at least five thousand but below twenty-five thousand, and one percent at
    twenty-five thousand or more."

    Design: Difficulty/combinatorial_formula/cut_to_length_per_segment_rounding_order_mode_b
    """
    world = setup_baseline(api, order_overrides=CUT_ORDER)
    order = world["order"]
    lot = create_lot(api, world, lot_code="LOT-CUT", planned_length_ft=3750)
    advance_lot_to_tested(api, lot["id"])
    release_lot(api, lot["id"], 3750)
    reel = create_reel(api, reel_serial="R-CUT")
    get_success_data(
        api.load_reel(reel["id"], load_reel_payload(lot["id"], 3750), CLERK)
    )
    shipment = validate_success(
        api.create_shipment(
            create_shipment_payload(
                order["id"], lot["id"], reel["id"], 3750,
                current_order_version(api, order["id"]),
                ship_date="2026-08-05", cuts_count=3,
            ),
            CLERK,
        ),
        201,
    )
    invoice = get_success_data(api.invoice_shipment(shipment["id"], BILLING))

    assert_four_decimal_price(
        invoice["unit_price_usd_per_kft"], 106.7800, "the locked unit price"
    )
    assert_money(
        invoice["extended_amount_usd"], 400.44,
        "three segments of 133.48, each rounded before it entered the sum",
    )
    assert invoice["extended_amount_usd"] != 400.43, (
        "rounding the sum once instead of each segment loses a cent"
    )
    assert_money(invoice["cut_fee_usd"], 37.50, "12.50 for each of three cuts")
    assert_money(invoice["volatility_surcharge_usd"], 8.01, "two percent of 400.44")
    assert_money(invoice["invoice_amount_usd"], 445.95, "the cut-to-length invoice")


def test_the_surcharge_tier_reads_the_subtotal_and_not_the_total_it_produces(api):
    """A subtotal of 4995.00 sits in the two percent band for 99.90. Reading the tier
    off the resulting 5094.90 total would drop to one and a half percent and
    answer 74.93 instead.

    PRD 3.5: "**Step four applies the metal volatility surcharge**, and its tier is
    keyed on `quoted_subtotal_usd` alone — before the cut fee and before the
    surcharge itself are added."

    PRD 3.5: "A subtotal below five thousand dollars carries a surcharge of two
    percent; a subtotal of five thousand dollars or more but below twenty-five
    thousand dollars carries one and a half percent; a subtotal of twenty-five
    thousand dollars or more carries one percent."

    Design: Difficulty/combinatorial_formula/surcharge_tier_keyed_on_pre_surcharge_subtotal_mode_c
    """
    world = setup_baseline(
        api,
        order_overrides={
            "order_number": "SO-TIER",
            "ordered_kft": 49.95,
            "conversion_price_usd_per_kft": 78.22,
        },
    )
    order = world["order"]

    assert_four_decimal_price(
        order["quoted_unit_price_usd_per_kft"], 100.0000, "78.22 plus 19.8 x 1.10"
    )
    assert_money(order["quoted_subtotal_usd"], 4995.00, "100.00 over 49.95 kft")
    assert_money(order["quoted_surcharge_usd"], 99.90, "two percent of 4995.00")
    assert order["quoted_surcharge_usd"] != 74.93, (
        "74.93 is one and a half percent of the total, which would be circular"
    )
    assert_money(order["quoted_cut_fee_usd"], 0.00, "this order is not cut to length")
    assert_money(order["quoted_total_usd"], 5094.90, "subtotal plus surcharge")


def test_the_smaller_order_can_carry_the_larger_surcharge_across_the_tier_edge(api):
    """Five feet more cable moves the subtotal from 4995.00 to 5000.00, which crosses
    into the lower rate and reduces the surcharge from 99.90 to 75.00.

    PRD 3.5: "A subtotal below five thousand dollars carries a surcharge of two
    percent; a subtotal of five thousand dollars or more but below twenty-five
    thousand dollars carries one and a half percent; a subtotal of twenty-five
    thousand dollars or more carries one percent."

    PRD 3.5: "`quoted_surcharge_usd` is the subtotal multiplied by that rate,
    rounded half up to two decimals, and the tier is chosen from the already-rounded
    subtotal."

    Design: Difficulty/combinatorial_formula/surcharge_tier_keyed_on_pre_surcharge_subtotal_mode_c
    """
    world = setup_baseline(
        api,
        order_overrides={
            "order_number": "SO-UNDER",
            "ordered_kft": 49.95,
            "conversion_price_usd_per_kft": 78.22,
        },
    )
    under_the_edge = world["order"]
    on_the_edge = create_order(
        api, world["customer"]["id"], world["product"]["id"],
        order_number="SO-EDGE", ordered_kft=50.000,
        conversion_price_usd_per_kft=78.22,
    )

    assert_money(under_the_edge["quoted_subtotal_usd"], 4995.00, "subtotal")
    assert_money(under_the_edge["quoted_surcharge_usd"], 99.90, "two percent")
    assert_money(on_the_edge["quoted_subtotal_usd"], 5000.00, "subtotal")
    assert_money(
        on_the_edge["quoted_surcharge_usd"], 75.00,
        "a subtotal of exactly five thousand is already in the lower band",
    )
    assert on_the_edge["quoted_surcharge_usd"] < under_the_edge["quoted_surcharge_usd"], (
        "the larger order carries the smaller surcharge because the tier is a step"
    )
    assert_money(on_the_edge["quoted_total_usd"], 5075.00, "subtotal plus surcharge")


def test_one_sku_lands_inside_the_target_band_while_another_is_cut_to_the_ceiling(api):
    """The same demand tier and the same base target produce 149.8 for a copper SKU
    whose metal market is choppy and a ceiling-clamped 150.0 for an aluminium SKU
    whose series is too short to characterise at all.

    PRD 3.4: "If the window holds fewer than three quotes there is not enough
    history to characterise volatility and `volatility_index` is set to 0.0000."

    PRD 3.4: "A demand multiplier is chosen from `demand_index`: 0.30 when
    `demand_index` is strictly below 0.80, 1.00 when it is at least 0.80 and at most
    1.20, and 1.80 when it is strictly above 1.20."

    PRD 3.4: "That raw figure is clamped between a floor of `base_target_kft`
    multiplied by 0.25 rounded half up to one decimal and a ceiling of
    `base_target_kft` multiplied by 1.50 rounded half up to one decimal — the clamp
    is applied first — and the clamped result is then rounded half up to one decimal
    place and stored as `target_inventory_kft`."

    Design: Difficulty/combinatorial_formula/inventory_target_ceiling_clamp_and_damper_mode_a
    """
    world = setup_lv_catalog(api, product_overrides={"demand_index": 1.30})
    _post_series(api, VOLATILE_COPPER_SERIES)
    _post_series(
        api, (("2026-08-01", 1.00), ("2026-08-02", 1.10)), metal="ALUMINUM",
        source="LME",
    )
    aluminium = create_released_product(
        api, world["insulation"]["id"], world["certification"]["id"],
        demand_index=1.30, **ALUMINUM_SKU,
    )

    run = get_success_data(
        api.reposition_inventory({"as_of_date": "2026-08-05"}, ENGINEER)
    )
    assert run["evaluated_count"] == 2, "both SKUs are RELEASED"
    assert run["skipped_count"] == 0

    copper = read_product(api, world["product"]["id"])
    assert copper["volatility_index"] == 0.2097, (
        "a 0.90 range over a mean of 4.2916666... rounds to four decimals"
    )
    assert copper["target_inventory_kft"] == 149.8, (
        "100.0 x 1.80 x (1 - 0.8 x 0.2097) is 149.8032, inside the band"
    )

    refreshed_aluminium = read_product(api, aluminium["id"])
    assert refreshed_aluminium["volatility_index"] == 0.0000, (
        "two quotes are fewer than the three the window needs"
    )
    assert refreshed_aluminium["target_inventory_kft"] == 150.0, (
        "an undamped 100.0 x 1.80 is 180.0, which the ceiling cuts back"
    )
    assert refreshed_aluminium["target_inventory_kft"] != 180.0, (
        "the clamp runs before the final rounding, not after storage"
    )


def test_the_demand_step_moves_the_target_while_the_damper_stays_out_of_the_way(api):
    """With too short a price series to damp anything, a demand index sitting exactly
    on the tier edge keeps the base target while one point above it jumps to the
    highest tier and is clamped.

    PRD 3.4: "A demand multiplier is chosen from `demand_index`: 0.30 when
    `demand_index` is strictly below 0.80, 1.00 when it is at least 0.80 and at most
    1.20, and 1.80 when it is strictly above 1.20."

    PRD 3.4: "A volatility damper is then one minus the smaller of 0.40 and eight
    tenths of `volatility_index` — so violent metal markets pull the target down,
    but never by more than forty percent, and the damper is left unrounded."

    Design: Difficulty/combinatorial_formula/inventory_target_ceiling_clamp_and_damper_mode_a
    """
    world = setup_lv_catalog(api, product_overrides={"demand_index": 1.20})
    just_above = create_released_product(
        api, world["insulation"]["id"], world["certification"]["id"],
        product_code="THHN-10-CU", awg_size="10", conductor_lbs_per_kft=20.0,
        base_target_kft=100.0, demand_index=1.21,
    )

    run = get_success_data(
        api.reposition_inventory({"as_of_date": "2026-08-05"}, ENGINEER)
    )
    assert run["evaluated_count"] == 2

    on_the_edge = read_product(api, world["product"]["id"])
    assert on_the_edge["volatility_index"] == 0.0000, (
        "one settlement is fewer than the three the window needs"
    )
    assert on_the_edge["target_inventory_kft"] == 100.0, (
        "a demand index of exactly 1.20 is still in the middle tier, so an "
        "undamped target is the base target itself"
    )

    over_the_edge = read_product(api, just_above["id"])
    assert over_the_edge["target_inventory_kft"] == 150.0, (
        "1.21 is strictly above 1.20, so the raw 180.0 meets the ceiling"
    )


def test_a_saturated_damper_and_the_weakest_demand_are_lifted_to_the_floor(api):
    """A volatility index of 1.0000 saturates the damper at its forty percent cap and
    the weakest demand tier takes the raw target to 18.0, which the floor lifts
    back to 25.0.

    PRD 3.4: "Otherwise `volatility_index` is the highest
    `settlement_price_usd_per_lb` in the window minus the lowest, divided by the
    arithmetic mean of the prices in the window, rounded half up to four decimal
    places; the mean itself is not rounded before the division."

    PRD 3.4: "A volatility damper is then one minus the smaller of 0.40 and eight
    tenths of `volatility_index` — so violent metal markets pull the target down,
    but never by more than forty percent, and the damper is left unrounded."

    PRD 3.4: "The run reports back the `as_of_date` it used, an `evaluated_count`, a
    `skipped_count`, and the `product_ids` it actually evaluated."

    Design: Difficulty/combinatorial_formula/inventory_target_floor_clamp_with_damper_cap_mode_a
    """
    world = setup_lv_catalog(
        api,
        quote_overrides={
            "effective_date": "2026-08-01", "settlement_price_usd_per_lb": 2.00,
        },
        product_overrides={"demand_index": 0.50},
    )
    _post_series(api, SATURATING_COPPER_SERIES[1:])

    run = get_success_data(
        api.reposition_inventory(
            {"as_of_date": "2026-08-03", "product_ids": [world["product"]["id"]]},
            ENGINEER,
        )
    )
    assert run["as_of_date"] == "2026-08-03"
    assert run["evaluated_count"] == 1
    assert run["skipped_count"] == 0
    assert run["product_ids"] == [world["product"]["id"]]

    product = read_product(api, world["product"]["id"])
    assert product["volatility_index"] == 1.0000, (
        "a 4.00 range over a mean of 4.00 is exactly one"
    )
    assert product["target_inventory_kft"] == 25.0, (
        "100.0 x 0.30 x 0.60 is 18.0, which the floor of 25.0 lifts"
    )
    assert product["target_inventory_kft"] != 18.0, (
        "the raw figure is never stored unclamped"
    )


def test_the_damper_cap_holds_two_bases_apart_at_the_same_volatility(api):
    """One index of 1.0000 damps every SKU by the same capped forty percent, so the
    target that survives depends on the base and the demand tier: 60.0 inside the
    band for one SKU and a floor-clamped 5.0 for the other.

    PRD 3.4: "A volatility damper is then one minus the smaller of 0.40 and eight
    tenths of `volatility_index` — so violent metal markets pull the target down,
    but never by more than forty percent, and the damper is left unrounded."

    PRD 3.4: "The raw target is `base_target_kft` multiplied by the demand
    multiplier and then by the damper."

    PRD 3.4: "The window is every quote whose `metal` equals the SKU's
    `conductor_metal` and whose `effective_date` is on or before `as_of_date`,
    ordered by `effective_date` descending with `created_at` descending as the
    tie-break, then truncated to the first ten rows."

    Design: Difficulty/combinatorial_formula/inventory_target_floor_clamp_with_damper_cap_mode_a
    """
    world = setup_lv_catalog(
        api,
        quote_overrides={
            "effective_date": "2026-08-01", "settlement_price_usd_per_lb": 2.00,
        },
        product_overrides={"demand_index": 1.00},
    )
    _post_series(api, SATURATING_COPPER_SERIES[1:])
    small_base = create_released_product(
        api, world["insulation"]["id"], world["certification"]["id"],
        product_code="THHN-10-CU", awg_size="10", conductor_lbs_per_kft=20.0,
        base_target_kft=20.0, demand_index=0.50,
    )

    run = get_success_data(
        api.reposition_inventory({"as_of_date": "2026-08-03"}, ENGINEER)
    )
    assert run["evaluated_count"] == 2

    middle_tier = read_product(api, world["product"]["id"])
    assert middle_tier["volatility_index"] == 1.0000
    assert middle_tier["target_inventory_kft"] == 60.0, (
        "100.0 x 1.00 x 0.60 sits inside a band of 25.0 to 150.0"
    )

    clamped = read_product(api, small_base["id"])
    assert clamped["volatility_index"] == 1.0000, (
        "the window is shared: both SKUs draw copper settlements"
    )
    assert clamped["target_inventory_kft"] == 5.0, (
        "20.0 x 0.30 x 0.60 is 3.6, which the floor of 20.0 x 0.25 lifts"
    )
