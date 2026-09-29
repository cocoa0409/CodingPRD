"""Derived arithmetic: spec-match scoring, waterfalls, tiers, caps and ledgers."""
import pytest

from test_helpers import (
    AM_HEADERS,
    CM_HEADERS,
    PA_HEADERS,
    WH_HEADERS,
    add_contract_hop_line,
    add_malt_line,
    add_reading,
    add_spot_hop_line,
    analyse_lot,
    approve_credit,
    cancel_order,
    confirm_order,
    create_brewer,
    create_contract,
    create_lot,
    create_malt_product,
    create_order,
    create_program,
    create_recipe,
    create_released_lot,
    create_strain,
    create_variety,
    create_zone,
    depart_shipment,
    get_brewer,
    get_order,
    make_brewer_headers,
    pick_order,
    pin_clock,
    report_harvest,
    request_carry_forward,
    ship_order,
    stage_shipment,
    validate_error,
    validate_paginated,
    validate_success,
)

CONFORMING_SHEET = {
    "color_lovibond": 2.60,
    "extract_pct": 79.90,
    "moisture_pct": 4.20,
    "protein_pct": 11.10,
    "diastatic_power": 95.00,
}


@pytest.fixture
def lot_scored_against_a_recipe():
    """A PASSED lot and an all-malt recipe targeting 2.50 / 80.00 / 11.00."""
    pin_clock()
    brewer = create_brewer(name="Spec Match Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    product = create_malt_product()
    strain = create_strain()
    recipe = create_recipe(brewer["id"], product["id"], strain["id"],
                           name="House Ale", batch_volume_bbl=30.00,
                           original_gravity_plato=12.50,
                           target_color_lovibond=2.50, target_extract_pct=80.00,
                           target_protein_pct=11.00,
                           requested_pitch_rate_million_cells_per_ml_per_plato=0.75,
                           adjunct_pct=0.0)
    return {"brewer": brewer, "product": product, "strain": strain,
            "recipe": recipe}


def test_three_small_deviations_are_weighted_and_rounded_once_into_acceptable(
        api, lot_scored_against_a_recipe):
    """0.0667, 0.1000 and 0.1250 weight to 90.71, which is ACCEPTABLE and not EXACT.

    PRD §3.6: "The weighted penalty is the colour deviation multiplied by 0.40,
    plus the extract deviation multiplied by 0.35, plus the protein deviation
    multiplied by 0.25 — three weights that sum to exactly 1.00, so a perfect lot
    scores 100.00."

    PRD §3.6: "`match_grade` is then `EXACT` when the score is at least 95.00,
    `ACCEPTABLE` when it is at least 80.00, `SUBSTITUTE_REQUIRED` when it is at
    least 60.00, and `REJECTED` otherwise."

    Design: Corner/calculations/spec_match_score_of_a_conforming_lot_grades_acceptable
    """
    world = lot_scored_against_a_recipe
    lot = create_lot(world["product"]["id"], quantity_lbs=5000,
                     lot_code="LOT-SM-1")
    analysed = analyse_lot(lot["id"], **CONFORMING_SHEET)
    assert analysed["status"] == "PASSED", (
        f"the lot clears both hard fails, got {analysed['status']}")

    scored = validate_success(api.spec_match(
        lot["id"], WH_HEADERS, params={"recipe_id": world["recipe"]["id"]}))
    assert scored["malt_lot_id"] == lot["id"], (
        f"the scored lot is echoed, got {scored['malt_lot_id']}")
    assert scored["recipe_id"] == world["recipe"]["id"], (
        f"the recipe is echoed, got {scored['recipe_id']}")
    assert scored["deviation_color"] == pytest.approx(0.0667, abs=0.00005), (
        f"0.10 over a 1.5 tolerance is 0.0667, got {scored['deviation_color']}")
    assert scored["deviation_extract"] == pytest.approx(0.1000, abs=0.00005), (
        f"0.10 over a 1.0 tolerance is 0.1000, got {scored['deviation_extract']}")
    assert scored["deviation_protein"] == pytest.approx(0.1250, abs=0.00005), (
        f"0.10 over a 0.8 tolerance is 0.1250, got {scored['deviation_protein']}")
    assert scored["match_score"] == pytest.approx(90.71, abs=0.005), (
        "100 less the 0.09293 weighted penalty is 90.707, rounded once to 90.71, "
        f"got {scored['match_score']}")
    assert scored["match_grade"] == "ACCEPTABLE", (
        f"90.71 clears 80.00 but not 95.00, got {scored['match_grade']}")
    assert scored["applicable_diastatic_power_floor"] == pytest.approx(60.0, abs=0.005), (
        "an all-malt recipe uses the product floor, got "
        f"{scored['applicable_diastatic_power_floor']}")
    assert scored["hard_fail_reason"] is None, (
        f"neither hard fail fired, got {scored['hard_fail_reason']}")

    after = validate_success(api.get_malt_lot(lot["id"], WH_HEADERS))
    assert after["version"] == analysed["version"], (
        f"scoring is a side-effect-free read, got version {after['version']}")
    assert after["status"] == "PASSED", (
        f"the lot's status is untouched, got {after['status']}")


def test_a_lot_sitting_exactly_on_every_target_scores_a_perfect_hundred(
        api, lot_scored_against_a_recipe):
    """Zero deviation on all three attributes gives 100.00 and the EXACT grade.

    PRD §3.6: "three weights that sum to exactly 1.00, so a perfect lot scores
    100.00"

    Design: Corner/calculations/spec_match_score_of_a_conforming_lot_grades_acceptable
    """
    world = lot_scored_against_a_recipe
    lot = create_lot(world["product"]["id"], quantity_lbs=5000,
                     lot_code="LOT-SM-2")
    analyse_lot(lot["id"], color_lovibond=2.50, extract_pct=80.00,
                moisture_pct=4.20, protein_pct=11.00, diastatic_power=95.00)

    scored = validate_success(api.spec_match(
        lot["id"], WH_HEADERS, params={"recipe_id": world["recipe"]["id"]}))
    assert scored["deviation_color"] == pytest.approx(0.0, abs=0.00005), (
        f"the colour is exactly on target, got {scored['deviation_color']}")
    assert scored["deviation_extract"] == pytest.approx(0.0, abs=0.00005), (
        f"the extract is exactly on target, got {scored['deviation_extract']}")
    assert scored["deviation_protein"] == pytest.approx(0.0, abs=0.00005), (
        f"the protein is exactly on target, got {scored['deviation_protein']}")
    assert scored["match_score"] == pytest.approx(100.00, abs=0.005), (
        f"a perfect lot scores 100.00, got {scored['match_score']}")
    assert scored["match_grade"] == "EXACT", (
        f"100.00 is at least 95.00, got {scored['match_grade']}")
    assert scored["hard_fail_reason"] is None, (
        f"no hard fail fired, got {scored['hard_fail_reason']}")


def test_a_wildly_off_colour_costs_at_most_its_own_weight(
        api, lot_scored_against_a_recipe):
    """2.3333 tolerance widths report as a capped 1.0000 and floor the score at 53.38.

    PRD §3.6: "Each deviation is carried to four decimal places and is capped at 1
    **individually, before weighting**: a wildly off-specification colour
    therefore costs at most its own weight and cannot drag the total negative.
    Capping the weighted sum instead of the individual deviations is incorrect."

    Design: Corner/calculations/spec_match_caps_each_deviation_individually_before_weighting
    """
    world = lot_scored_against_a_recipe
    lot = create_lot(world["product"]["id"], quantity_lbs=5000,
                     lot_code="LOT-CD-1")
    analyse_lot(lot["id"], color_lovibond=6.00, extract_pct=79.90,
                moisture_pct=4.20, protein_pct=11.10, diastatic_power=95.00)

    scored = validate_success(api.spec_match(
        lot["id"], WH_HEADERS, params={"recipe_id": world["recipe"]["id"]}))
    assert scored["deviation_color"] == pytest.approx(1.0000, abs=0.00005), (
        f"the raw 2.3333 is capped to 1.0000, got {scored['deviation_color']}")
    assert scored["match_score"] == pytest.approx(53.38, abs=0.005), (
        "100 less the 0.46625 weighted penalty is 53.375, rounded to 53.38, got "
        f"{scored['match_score']}")
    assert scored["match_score"] > 0, (
        f"a per-attribute cap cannot drive the score negative, got "
        f"{scored['match_score']}")
    assert scored["match_grade"] == "REJECTED", (
        f"53.38 is below the 60.00 gate, got {scored['match_grade']}")
    assert scored["hard_fail_reason"] is None, (
        "colour is a scoring attribute, not a hard fail, got "
        f"{scored['hard_fail_reason']}")

    after = validate_success(api.get_malt_lot(lot["id"], WH_HEADERS))
    assert after["status"] == "PASSED", (
        f"a poor score is not a quality gate, got {after['status']}")


def test_an_adjunct_recipe_raises_the_floor_and_hard_fails_the_same_lot(
        api, lot_scored_against_a_recipe):
    """65.0 diastatic power scores 90.71 all-malt and hard-fails a 25 percent adjunct grist.

    PRD §3.6: "The second is a lot whose `diastatic_power` is strictly below the
    applicable floor, where that floor is the product's `min_diastatic_power`
    normally but is raised by 10.0 degrees Lintner when the recipe's `adjunct_pct`
    is greater than zero; the floor actually used is what
    `applicable_diastatic_power_floor` reports."

    PRD §3.6: "Two hard failures are evaluated first, in exactly this order, and
    when either fires the score is not computed at all and `match_grade` is
    `REJECTED`."

    Design: Corner/calculations/adjunct_recipe_raises_the_diastatic_floor_and_hard_fails_the_lot
    """
    world = lot_scored_against_a_recipe
    adjunct_recipe = create_recipe(
        world["brewer"]["id"], world["product"]["id"], world["strain"]["id"],
        name="Corn Lager", batch_volume_bbl=30.00, original_gravity_plato=12.50,
        target_color_lovibond=2.50, target_extract_pct=80.00,
        target_protein_pct=11.00,
        requested_pitch_rate_million_cells_per_ml_per_plato=0.75,
        adjunct_pct=25.0)
    lot = create_lot(world["product"]["id"], quantity_lbs=5000,
                     lot_code="LOT-AF-1")
    analyse_lot(lot["id"], color_lovibond=2.60, extract_pct=79.90,
                moisture_pct=4.20, protein_pct=11.10, diastatic_power=65.00)

    plain = validate_success(api.spec_match(
        lot["id"], WH_HEADERS, params={"recipe_id": world["recipe"]["id"]}))
    assert plain["applicable_diastatic_power_floor"] == pytest.approx(60.0, abs=0.005), (
        "an all-malt grist uses the product floor, got "
        f"{plain['applicable_diastatic_power_floor']}")
    assert plain["hard_fail_reason"] is None, (
        f"65.0 clears 60.0, got {plain['hard_fail_reason']}")
    assert plain["match_score"] == pytest.approx(90.71, abs=0.005), (
        f"the same three deviations score 90.71, got {plain['match_score']}")

    adjunct = validate_success(api.spec_match(
        lot["id"], WH_HEADERS, params={"recipe_id": adjunct_recipe["id"]}))
    assert adjunct["applicable_diastatic_power_floor"] == pytest.approx(70.0, abs=0.005), (
        "60.0 plus the 10.0 adjunct bonus is 70.0, got "
        f"{adjunct['applicable_diastatic_power_floor']}")
    assert adjunct["hard_fail_reason"] == "DIASTATIC_POWER_BELOW_MIN", (
        f"65.0 is below the raised floor, got {adjunct['hard_fail_reason']}")
    assert adjunct["match_grade"] == "REJECTED", (
        f"a hard fail grades REJECTED, got {adjunct['match_grade']}")
    assert adjunct["match_score"] is None, (
        f"a hard fail short-circuits scoring, got {adjunct['match_score']}")
    assert adjunct["deviation_color"] is None and \
        adjunct["deviation_extract"] is None and \
        adjunct["deviation_protein"] is None, (
        "no deviation is computed on a hard fail, got "
        f"{adjunct['deviation_color']}, {adjunct['deviation_extract']}, "
        f"{adjunct['deviation_protein']}")

    after = validate_success(api.get_malt_lot(lot["id"], WH_HEADERS))
    assert after["status"] == "PASSED", (
        "analysis reads the product floor, not the recipe's, got "
        f"{after['status']}")
    assert after["quarantine_reason"] is None, (
        f"65.0 cleared the product floor, got {after['quarantine_reason']}")


def test_a_draft_line_never_consumes_the_lot_but_a_confirmed_one_does(api):
    """5000 available with a DRAFT line, 3500 once a 1500 lb line is confirmed.

    PRD §3.6: "Lines on a `DRAFT` order are deliberately excluded — malt is not
    reserved until an order is confirmed — so two breweries can each hold draft
    lines against the same lot, and the second one to confirm is the one that
    fails with `ERR_MALT_LOT_INSUFFICIENT_QUANTITY`."

    PRD §3.6: "Lines in `CANCELLED_SHORTFALL`, `REMOVED` or `QUARANTINED` are
    excluded too, so cancelling or trimming a line returns its poundage to
    `available_lbs`."

    Design: Corner/calculations/malt_lot_availability_excludes_lines_on_draft_orders
    """
    pin_clock()
    brewer = create_brewer(name="Availability Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    product = create_malt_product()
    lot = create_released_lot(product["id"], quantity_lbs=5000,
                             lot_code="LOT-AV-1", **CONFORMING_SHEET)
    draft = create_order(brewer["id"], requested_ship_date="2026-09-20T00:00:00Z",
                         purchase_order_ref="PO-AV-D")
    draft_line = add_malt_line(draft["id"], brewer["id"], lot["id"], 1000)
    confirmed = create_order(brewer["id"],
                             requested_ship_date="2026-09-20T00:00:00Z",
                             purchase_order_ref="PO-AV-C")
    add_malt_line(confirmed["id"], brewer["id"], lot["id"], 1500)

    before = validate_success(api.get_malt_lot(lot["id"], WH_HEADERS))
    assert before["committed_lbs"] == 0, (
        "the 1000 lb draft line is outside the input set, got "
        f"{before['committed_lbs']}")
    assert before["available_lbs"] == 5000, (
        f"the whole lot is still available, got {before['available_lbs']}")

    order = confirm_order(confirmed["id"], brewer["id"])
    assert order["subtotal_cents"] == 102750, (
        f"1500 lbs at 68.50 is 102750, got {order['subtotal_cents']}")

    during = validate_success(api.get_malt_lot(lot["id"], WH_HEADERS))
    assert during["committed_lbs"] == 1500, (
        "only the confirmed line counts, not 2500, got "
        f"{during['committed_lbs']}")
    assert during["available_lbs"] == 3500, (
        f"5000 less 1500 leaves 3500, got {during['available_lbs']}")

    cancel_order(confirmed["id"], cancel_reason="brewer deferred the brew")
    after = validate_success(api.get_malt_lot(lot["id"], WH_HEADERS))
    assert after["committed_lbs"] == 0, (
        f"the REMOVED line leaves the input set, got {after['committed_lbs']}")
    assert after["available_lbs"] == 5000, (
        f"the poundage returns in full, got {after['available_lbs']}")
    assert after["quantity_lbs"] == 5000, (
        f"the received quantity never changes, got {after['quantity_lbs']}")

    still_draft = get_order(draft["id"], make_brewer_headers(brewer["id"]))
    assert still_draft["fulfillment_status"] == "DRAFT", (
        f"the untouched order is still DRAFT, got {still_draft['fulfillment_status']}")
    surviving = validate_success(api.get_order_line(
        draft_line["id"], make_brewer_headers(brewer["id"])))
    assert surviving["status"] == "OPEN", (
        f"its line is still open, got {surviving['status']}")


def test_both_freight_tier_gates_are_inclusive_lower_bounds(api):
    """39999 lbs is TIER_1, exactly 40000 is TIER_2 and exactly 120000 is TIER_3.

    PRD §3.1: "From that total, `freight_program_tier` is `TIER_3` when the
    trailing volume is at least 120,000 pounds, otherwise `TIER_2` when it is at
    least 40,000 pounds, otherwise `TIER_1`; the comparison is a plain "at least"
    on the summed poundage with no rounding."

    PRD §3.1: "The only way to change `legacy_trailing_lbs` after registration is a
    volume adjustment, an `AllocationManager` or `PlatformAdmin` capability that
    rewrites the figure to a supplied `legacy_trailing_lbs` with an optional
    `reason`, then re-rates `trailing_12mo_volume_lbs` and
    `freight_program_tier`."

    Design: Corner/calculations/freight_tier_threshold_promotes_at_exactly_forty_thousand_pounds
    """
    pin_clock()
    brewer = create_brewer(name="Freight Gate Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=False, legacy_trailing_lbs=0)
    assert brewer["freight_program_tier"] == "TIER_1", (
        f"an empty history is TIER_1, got {brewer['freight_program_tier']}")

    low = validate_success(api.post_volume_adjustment(
        brewer["id"], {"legacy_trailing_lbs": 39999,
                       "reason": "one pound short of the gate"}, PA_HEADERS))
    assert low["trailing_12mo_volume_lbs"] == 39999, (
        f"the seeded figure is echoed, got {low['trailing_12mo_volume_lbs']}")
    assert low["freight_program_tier"] == "TIER_1", (
        f"39999 has not reached 40000, got {low['freight_program_tier']}")

    mid = validate_success(api.post_volume_adjustment(
        brewer["id"], {"legacy_trailing_lbs": 40000,
                       "reason": "exactly at the tier gate"}, PA_HEADERS))
    assert mid["freight_program_tier"] == "TIER_2", (
        "the boundary pound belongs to the higher tier, got "
        f"{mid['freight_program_tier']}")

    high = validate_success(api.post_volume_adjustment(
        brewer["id"], {"legacy_trailing_lbs": 120000,
                       "reason": "exactly at the top gate"}, PA_HEADERS))
    assert high["freight_program_tier"] == "TIER_3", (
        f"120000 is at least 120000, got {high['freight_program_tier']}")
    assert high["version"] == 4, (
        "registration plus three adjustments is version 4, got "
        f"{high['version']}")
    assert high["ar_balance_cents"] == 0, (
        f"a re-rating touches no money, got {high['ar_balance_cents']}")
    assert high["credit_exposure_cents"] == 0, (
        f"nor any exposure, got {high['credit_exposure_cents']}")
    assert high["credit_status"] == "GOOD_STANDING", (
        f"nor the credit posture, got {high['credit_status']}")


def test_the_applied_tier_changes_both_the_freight_rate_and_its_minimum(api):
    """The same 1000 lb malt order costs 5000 in freight at TIER_3 and 25000 at TIER_1.

    PRD §3.8: "Seventh, the rated freight is `chargeable_lbs` multiplied by the
    rate for the applied tier — 12 cents per pound for `TIER_1`, 8 for `TIER_2`, 5
    for `TIER_3` — rounded half up to whole cents. Eighth, `freight_cents` is the
    greater of the applied tier's freight minimum — 25,000 cents for `TIER_1`,
    15,000 for `TIER_2`, 0 for `TIER_3` — and that rated freight."

    Design: Corner/calculations/freight_tier_threshold_promotes_at_exactly_forty_thousand_pounds
    """
    pin_clock()
    product = create_malt_product()
    lot = create_released_lot(product["id"], quantity_lbs=5000,
                             lot_code="LOT-FR-1", **CONFORMING_SHEET)

    top = create_brewer(name="Top Tier Brewing", credit_limit_cents=5000000,
                        cold_chain_certified=False, legacy_trailing_lbs=120000)
    assert top["freight_program_tier"] == "TIER_3", (
        f"the seeded volume rates TIER_3, got {top['freight_program_tier']}")
    top_order = create_order(top["id"],
                             requested_ship_date="2026-09-20T00:00:00Z",
                             purchase_order_ref="PO-FR-3")
    add_malt_line(top_order["id"], top["id"], lot["id"], 1000)
    top_order = confirm_order(top_order["id"], top["id"])
    assert top_order["freight_tier_applied"] == "TIER_3", (
        f"the order prices at TIER_3, got {top_order['freight_tier_applied']}")
    assert top_order["freight_cents"] == 5000, (
        "1000 lbs at 5 cents beats a zero minimum, got "
        f"{top_order['freight_cents']}")
    assert top_order["total_cents"] == 85500, (
        "68500 plus 5000 freight, 4500 pallet break and 7500 surcharge = 85500, "
        f"got {top_order['total_cents']}")

    base = create_brewer(name="Base Tier Brewing", credit_limit_cents=5000000,
                         cold_chain_certified=False, legacy_trailing_lbs=0)
    base_order = create_order(base["id"],
                              requested_ship_date="2026-09-20T00:00:00Z",
                              purchase_order_ref="PO-FR-1")
    add_malt_line(base_order["id"], base["id"], lot["id"], 1000)
    base_order = confirm_order(base_order["id"], base["id"])
    assert base_order["freight_tier_applied"] == "TIER_1", (
        f"an empty history prices at TIER_1, got {base_order['freight_tier_applied']}")
    assert base_order["freight_cents"] == 25000, (
        "the 12-cent rating of 12000 is lifted to the 25000 minimum, got "
        f"{base_order['freight_cents']}")
    assert base_order["total_cents"] == 105500, (
        "68500 plus 25000 freight, 4500 pallet break and 7500 surcharge = 105500, "
        f"got {base_order['total_cents']}")
    assert base_order["subtotal_cents"] == top_order["subtotal_cents"], (
        "the two orders differ only in freight, got "
        f"{base_order['subtotal_cents']} and {top_order['subtotal_cents']}")


def test_a_short_crop_bites_the_spot_holder_whole_before_the_fixed_contract(api):
    """12000 lbs fill the 10000 lb fixed book first, leaving the spot hold 3000 short.

    PRD §3.3: "Every `FIXED_CROP_YEAR` contract is filled to its full
    `contracted_lbs` before **any** `SPOT_HOLD` contract receives a single pound: a
    shortfall therefore lands entirely on the spot holders until they are
    exhausted, and only then bites into fixed commitments. Distributing the
    shortfall proportionally across all contracts is incorrect."

    Design: Corner/calculations/shortfall_waterfall_fills_fixed_commitments_before_spot_holds
    """
    pin_clock()
    brewer = create_brewer(name="Waterfall Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    program = create_program(crop_year=2026)
    citra = create_variety()
    mosaic = create_variety(variety_code="MOSAIC", name="Mosaic",
                            alpha_acid_target_pct=12.00,
                            spot_price_cents_per_lb=450.00)
    fixed = create_contract(brewer["id"], citra["id"], program["id"],
                            contracted_lbs=10000, price_per_lb_cents=285.50,
                            contract_type="FIXED_CROP_YEAR",
                            delivery_window_start="2026-09-01T00:00:00Z",
                            delivery_window_end="2026-12-31T00:00:00Z")
    spot = create_contract(brewer["id"], mosaic["id"], program["id"],
                           contracted_lbs=5000, price_per_lb_cents=450.00,
                           contract_type="SPOT_HOLD",
                           delivery_window_start="2026-09-01T00:00:00Z",
                           delivery_window_end="2026-12-31T00:00:00Z")

    reported = report_harvest(program["id"], harvest_yield_pct=80.00,
                              reported_note="crop down a fifth")
    assert reported["status"] == "HARVEST_REPORTED", (
        f"the program advances on the report, got {reported['status']}")
    assert reported["total_contracted_lbs"] == 15000, (
        f"10000 plus 5000 is the contract base, got {reported['total_contracted_lbs']}")
    assert reported["allocatable_pool_lbs"] == 12000, (
        f"80 percent of 15000 floors to 12000, got {reported['allocatable_pool_lbs']}")
    assert reported["unallocated_pool_lbs"] == 0, (
        "a short crop leaves no remainder, got "
        f"{reported['unallocated_pool_lbs']}")
    assert reported["harvest_yield_pct"] == pytest.approx(80.00, abs=0.005), (
        f"the reported yield is stamped, got {reported['harvest_yield_pct']}")
    assert reported["harvest_reported_at"].startswith("2026-08-01T00:00:00"), (
        "the report is stamped with the logical clock, got "
        f"{reported['harvest_reported_at']}")

    after_fixed = validate_success(api.get_hop_contract(fixed["id"], AM_HEADERS))
    assert after_fixed["allocated_lbs"] == 10000, (
        "the fixed book is filled whole rather than pro-rated to 8000, got "
        f"{after_fixed['allocated_lbs']}")
    assert after_fixed["shortfall_lbs"] == 0, (
        f"and is therefore not short at all, got {after_fixed['shortfall_lbs']}")
    assert after_fixed["remaining_lbs"] == 10000, (
        f"all of it is still available to draw, got {after_fixed['remaining_lbs']}")
    assert after_fixed["status"] == "ACTIVE", (
        f"an unshorted contract does not change state, got {after_fixed['status']}")

    after_spot = validate_success(api.get_hop_contract(spot["id"], AM_HEADERS))
    assert after_spot["allocated_lbs"] == 2000, (
        "the spot holder takes what survives the waterfall, not a pro-rata 4000, "
        f"got {after_spot['allocated_lbs']}")
    assert after_spot["shortfall_lbs"] == 3000, (
        f"5000 less 2000 is a 3000 lb shortfall, got {after_spot['shortfall_lbs']}")
    assert after_spot["remaining_lbs"] == 2000, (
        f"the drawable poundage follows the allocation, got {after_spot['remaining_lbs']}")
    assert after_spot["status"] == "SHORTFALL_ADJUSTED", (
        f"only the shorted contract changes state, got {after_spot['status']}")


def test_a_bumper_crop_parks_the_surplus_instead_of_over_allocating(api):
    """A 120 percent yield on 10000 lbs allocates 10000 and parks 2000 unallocated.

    PRD §3.3: "Walking that order, each contract's `allocated_lbs` becomes the
    lesser of the poundage left in the pool and its own `contracted_lbs`; the pool
    is reduced by that amount; and the contract's `shortfall_lbs` becomes its
    `contracted_lbs` less its `allocated_lbs`. Whatever poundage survives the last
    contract becomes the program's `unallocated_pool_lbs`, which is 0 unless
    `harvest_yield_pct` exceeded 100."

    Design: Corner/calculations/harvest_above_one_hundred_percent_leaves_an_unallocated_remainder
    """
    pin_clock()
    brewer = create_brewer(name="Bumper Crop Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    program = create_program(crop_year=2026)
    citra = create_variety()
    contract = create_contract(brewer["id"], citra["id"], program["id"],
                               contracted_lbs=10000, price_per_lb_cents=285.50,
                               contract_type="FIXED_CROP_YEAR",
                               delivery_window_start="2026-09-01T00:00:00Z",
                               delivery_window_end="2026-12-31T00:00:00Z")

    reported = report_harvest(program["id"], harvest_yield_pct=120.00,
                              reported_note="an exceptional year")
    assert reported["allocatable_pool_lbs"] == 12000, (
        f"120 percent of 10000 is 12000, got {reported['allocatable_pool_lbs']}")
    assert reported["unallocated_pool_lbs"] == 2000, (
        "the 2000 lb surplus survives the last contract, got "
        f"{reported['unallocated_pool_lbs']}")
    assert reported["total_contracted_lbs"] == 10000, (
        f"the contract base is unchanged, got {reported['total_contracted_lbs']}")

    after = validate_success(api.get_hop_contract(contract["id"], AM_HEADERS))
    assert after["allocated_lbs"] == 10000, (
        "the allocation is capped at what was bought rather than promoted to "
        f"12000, got {after['allocated_lbs']}")
    assert after["shortfall_lbs"] == 0, (
        f"a filled contract is not short, got {after['shortfall_lbs']}")
    assert after["remaining_lbs"] == 10000, (
        f"the whole commitment is drawable, got {after['remaining_lbs']}")
    assert after["status"] == "ACTIVE", (
        "no SHORTFALL_ADJUSTED cascade fires on a bumper crop, got "
        f"{after['status']}")


def test_the_allocatable_pool_floors_a_fractional_pound_rather_than_rounding(api):
    """99.99 percent of 10000 lbs is 9999.0, so the pool is 9999 and one pound short.

    PRD §3.3: "It then freezes `allocatable_pool_lbs` at the total contracted
    poundage multiplied by `harvest_yield_pct`, divided by 100, and **floored** to
    a whole pound — a partial pound is never allocated."

    Design: Corner/calculations/harvest_above_one_hundred_percent_leaves_an_unallocated_remainder
    """
    pin_clock()
    brewer = create_brewer(name="Floored Pound Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    program = create_program(crop_year=2027)
    citra = create_variety()
    contract = create_contract(brewer["id"], citra["id"], program["id"],
                               contracted_lbs=10000, price_per_lb_cents=285.50,
                               contract_type="FIXED_CROP_YEAR",
                               delivery_window_start="2027-09-01T00:00:00Z",
                               delivery_window_end="2027-12-31T00:00:00Z")

    reported = report_harvest(program["id"], harvest_yield_pct=99.99,
                              reported_note="a hair under full")
    assert reported["allocatable_pool_lbs"] == 9999, (
        "9999.0 floors to 9999 rather than rounding to 10000, got "
        f"{reported['allocatable_pool_lbs']}")
    assert reported["unallocated_pool_lbs"] == 0, (
        f"the pool is fully drained, got {reported['unallocated_pool_lbs']}")

    after = validate_success(api.get_hop_contract(contract["id"], AM_HEADERS))
    assert after["allocated_lbs"] == 9999, (
        f"the contract takes the whole floored pool, got {after['allocated_lbs']}")
    assert after["shortfall_lbs"] == 1, (
        "the missing pound is a real shortfall, got "
        f"{after['shortfall_lbs']}")
    assert after["status"] == "SHORTFALL_ADJUSTED", (
        f"one pound short is still short, got {after['status']}")


def test_the_gap_is_charged_to_the_sample_that_closes_it_and_backdating_is_refused(api):
    """A clean 10:00, a violating 10:20 charging 20, a refused 10:10 and a free 10:20.

    PRD §3.9: "A reading's `recorded_at` must be at or after the load's
    `last_reading_at`; equal timestamps are accepted and contribute an
    `interval_minutes` of 0, and anything strictly earlier is refused with
    `ERR_READING_OUT_OF_ORDER`."

    PRD §3.9: "**The attribution is normative**: the interval is charged to the
    reading that *closes* it, so the time elapsed before the first out-of-tolerance
    sample is not penalised, but the whole gap leading up to a violating sample is
    charged in full."

    Design: Corner/calculations/excursion_assessment_replays_readings_in_recorded_order
    """
    pin_clock()
    brewer = create_brewer(name="Chronological Reading Brewing",
                           credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    variety = create_variety()
    zone = create_zone(zone_code="Z1", temp_setpoint_c=2.0, capacity_pallets=10,
                       tolerance_c=2.0)
    order = create_order(brewer["id"],
                         requested_ship_date="2026-09-12T00:00:00Z",
                         purchase_order_ref="PO-CR")
    add_spot_hop_line(order["id"], brewer["id"], variety["id"], 880)
    confirm_order(order["id"], brewer["id"])
    approve_credit(order["id"], note="within limit")
    pick_order(order["id"])
    shipment = stage_shipment(order["id"], zone["id"], pallet_count=1,
                              stage_from="2026-08-01T00:00:00Z",
                              stage_until="2026-08-02T00:00:00Z",
                              reefer_setpoint_c=2.00, reefer_tolerance_c=2.00)
    shipment = depart_shipment(shipment["id"])
    assert shipment["status"] == "IN_TRANSIT", (
        f"the load must be on the road to accept telemetry, got {shipment['status']}")

    first = add_reading(shipment["id"], 2.0, "2026-08-01T10:00:00Z")
    assert first["in_violation"] is False, (
        f"2.0 sits inside the band [0.0, 4.0], got {first['in_violation']}")
    assert first["interval_minutes"] == 0, (
        f"the first reading has no predecessor, got {first['interval_minutes']}")
    assert first["cumulative_excursion_minutes"] == 0, (
        f"nothing has accrued yet, got {first['cumulative_excursion_minutes']}")

    second = add_reading(shipment["id"], 9.5, "2026-08-01T10:20:00Z")
    assert second["in_violation"] is True, (
        f"9.5 is strictly above 4.0, got {second['in_violation']}")
    assert second["interval_minutes"] == 20, (
        f"10:00 to 10:20 is twenty whole minutes, got {second['interval_minutes']}")
    assert second["cumulative_excursion_minutes"] == 20, (
        "the whole gap leading up to the violating sample is charged, got "
        f"{second['cumulative_excursion_minutes']}")

    backdated = api.add_reading(shipment["id"],
                               {"temp_c": 3.0,
                                "recorded_at": "2026-08-01T10:10:00Z"},
                               WH_HEADERS)
    validate_error(backdated, "ERR_READING_OUT_OF_ORDER", expected_status=422)
    _, meta = validate_paginated(api.list_readings(shipment["id"], WH_HEADERS))
    assert meta["total_count"] == 2, (
        f"the refused sample stores no row, got {meta['total_count']}")

    duplicate = add_reading(shipment["id"], 9.0, "2026-08-01T10:20:00Z")
    assert duplicate["in_violation"] is True, (
        f"9.0 is also out of band, got {duplicate['in_violation']}")
    assert duplicate["interval_minutes"] == 0, (
        "an equal timestamp closes a zero-length interval, got "
        f"{duplicate['interval_minutes']}")
    assert duplicate["cumulative_excursion_minutes"] == 20, (
        "a violating sample with a zero interval contributes nothing, got "
        f"{duplicate['cumulative_excursion_minutes']}")

    load = validate_success(api.get_shipment(shipment["id"], WH_HEADERS))
    assert load["reading_count"] == 3, (
        f"three samples were stored, got {load['reading_count']}")
    assert load["excursion_minutes"] == 20, (
        "the load carries the latest cumulative figure, got "
        f"{load['excursion_minutes']}")
    assert load["last_reading_at"].startswith("2026-08-01T10:20:00"), (
        f"the series high-water mark is 10:20, got {load['last_reading_at']}")
    assert load["status"] == "IN_TRANSIT", (
        "twenty minutes has not passed the thirty-minute limit, got "
        f"{load['status']}")

    series, meta = validate_paginated(api.list_readings(shipment["id"], WH_HEADERS))
    assert meta["total_count"] == 3, (
        f"the listing agrees with the load, got {meta['total_count']}")
    stamps = [reading["recorded_at"] for reading in series]
    assert stamps == sorted(stamps), (
        f"the series is returned in recorded_at ascending order, got {stamps}")


@pytest.fixture
def contract_drawn_down_to_a_thousand_pounds():
    """A 5000 lb contract with 4000 committed, on a program that has reported."""
    pin_clock()
    brewer = create_brewer(name="Carry Forward Brewing", credit_limit_cents=3000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    program_2026 = create_program(crop_year=2026)
    program_2027 = create_program(crop_year=2027)
    variety = create_variety()
    contract = create_contract(brewer["id"], variety["id"], program_2026["id"],
                               contracted_lbs=5000, price_per_lb_cents=250.00,
                               contract_type="FIXED_CROP_YEAR",
                               delivery_window_start="2026-09-01T00:00:00Z",
                               delivery_window_end="2026-12-31T00:00:00Z")
    order = create_order(brewer["id"],
                        requested_ship_date="2026-09-20T00:00:00Z",
                        purchase_order_ref="PO-CF")
    add_contract_hop_line(order["id"], brewer["id"], variety["id"],
                          contract["id"], 4000)
    order = confirm_order(order["id"], brewer["id"])
    report_harvest(program_2026["id"], harvest_yield_pct=100.00,
                   reported_note="full crop")
    return {"brewer": brewer, "program_2026": program_2026,
            "program_2027": program_2027, "variety": variety,
            "contract": contract, "order": order}


def test_one_pound_above_the_eligible_figure_is_refused_outright(
        api, contract_drawn_down_to_a_thousand_pounds):
    """The cap is 1250 but only 1000 remains, so 1001 lbs cannot be rolled.

    PRD §3.5: "the eligible poundage is the lesser of that cap and the contract's
    current `remaining_lbs`. Requesting exactly the eligible figure is accepted;
    anything above it is not."

    Design: Corner/calculations/carry_forward_cap_is_a_share_of_the_original_contracted_pounds
    """
    world = contract_drawn_down_to_a_thousand_pounds
    assert world["order"]["total_cents"] == 1055500, (
        "985000 after the 1.5 percent discount, plus 66000 reefer freight and a "
        f"4500 pallet break, is 1055500, got {world['order']['total_cents']}")

    drawn = validate_success(api.get_hop_contract(world["contract"]["id"],
                                                 AM_HEADERS))
    assert drawn["committed_lbs"] == 4000, (
        f"the confirmed order holds 4000 lbs, got {drawn['committed_lbs']}")
    assert drawn["remaining_lbs"] == 1000, (
        f"5000 less 4000 leaves 1000 undrawn, got {drawn['remaining_lbs']}")
    assert drawn["allocated_lbs"] == 5000, (
        f"a full harvest allocates the whole commitment, got {drawn['allocated_lbs']}")
    assert drawn["status"] == "ACTIVE", (
        f"a full harvest shorts nothing, got {drawn['status']}")

    refused = api.request_carry_forward(
        world["contract"]["id"],
        {"carry_forward_target_program_id": world["program_2027"]["id"],
         "requested_lbs": 1001, "justification": "one pound too greedy"},
        make_brewer_headers(world["brewer"]["id"]))
    validate_error(refused, "ERR_CARRY_FORWARD_EXCEEDS_CAP", expected_status=422)

    unchanged = validate_success(api.get_hop_contract(world["contract"]["id"],
                                                      AM_HEADERS))
    assert unchanged["status"] == "ACTIVE", (
        f"the refusal leaves the contract where it was, got {unchanged['status']}")
    assert unchanged["carry_forward_requested_lbs"] is None, (
        "no request is recorded, got "
        f"{unchanged['carry_forward_requested_lbs']}")
    assert unchanged["carry_forward_fee_cents"] is None, (
        f"and no fee is priced, got {unchanged['carry_forward_fee_cents']}")


def test_the_cap_is_measured_against_the_original_commitment_not_the_remainder(
        api, contract_drawn_down_to_a_thousand_pounds):
    """A 1250 lb cap on the original 5000 admits all 1000 remaining pounds.

    PRD §3.5: "The cap itself is computed as 25 percent of the contract's
    **original** `contracted_lbs`, floored to a whole pound, and the eligible
    poundage is the lesser of that cap and the contract's current `remaining_lbs`."

    PRD §3.5: "Basing the cap on the currently-remaining poundage instead of the
    original commitment is incorrect: a brewery that has already drawn most of a
    contract can still roll the full capped amount so long as that much remains
    undrawn."

    Design: Corner/calculations/carry_forward_cap_is_a_share_of_the_original_contracted_pounds
    """
    world = contract_drawn_down_to_a_thousand_pounds
    pending = request_carry_forward(world["contract"]["id"], world["brewer"]["id"],
                                    world["program_2027"]["id"], 1000,
                                    justification="tank space next season")
    assert pending["status"] == "CARRY_FORWARD_PENDING", (
        "a cap of floor(5000 * 25 / 100) = 1250 admits 1000, where a cap read off "
        f"remaining_lbs would have allowed only 250, got {pending['status']}")
    assert pending["carry_forward_requested_lbs"] == 1000, (
        "the requested poundage is recorded, got "
        f"{pending['carry_forward_requested_lbs']}")
    assert pending["carry_forward_fee_cents"] == 20000, (
        "1000 lbs at 250.00 cents, taken at 8 percent, is 20000 cents, got "
        f"{pending['carry_forward_fee_cents']}")
    assert pending["carry_forward_target_program_id"] == world["program_2027"]["id"], (
        "the 2027 program is stamped as the target, got "
        f"{pending['carry_forward_target_program_id']}")
    assert pending["carried_forward_out_lbs"] == 0, (
        "nothing moves out until the desk decides, got "
        f"{pending['carried_forward_out_lbs']}")
    assert pending["remaining_lbs"] == 1000, (
        f"the poundage is still undrawn, got {pending['remaining_lbs']}")

    brewer = get_brewer(world["brewer"]["id"])
    assert brewer["ar_balance_cents"] == 0, (
        "the fee is booked on approval rather than on request, got "
        f"{brewer['ar_balance_cents']}")


@pytest.fixture
def draft_order_with_one_reefer_line_and_one_malt_line():
    """A DRAFT order carrying an 880 lb SPOT Citra line and a 1000 lb malt line."""
    pin_clock()
    brewer = create_brewer(name="Rollup Delete Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    variety = create_variety()
    product = create_malt_product()
    lot = create_released_lot(product["id"], quantity_lbs=5000,
                             lot_code="LOT-RD-1", **CONFORMING_SHEET)
    order = create_order(brewer["id"],
                        requested_ship_date="2026-09-20T00:00:00Z",
                        purchase_order_ref="PO-RD")
    hop_line = add_spot_hop_line(order["id"], brewer["id"], variety["id"], 880)
    malt_line = add_malt_line(order["id"], brewer["id"], lot["id"], 1000)
    return {"brewer": brewer, "variety": variety, "product": product, "lot": lot,
            "order": order, "hop_line": hop_line, "malt_line": malt_line}


def test_deleting_the_only_reefer_line_re_derives_the_whole_rollup(
        api, draft_order_with_one_reefer_line_and_one_malt_line):
    """The order drops to one line, 1000 chargeable lbs, 68500 and ambient freight.

    PRD §3.8: "Removing a line from a `DRAFT` order moves it `OPEN → REMOVED`,
    which is terminal, and re-runs the roll-up over what is left, rewriting
    `subtotal_cents`, `chargeable_lbs`, `line_count` and `requires_cold_chain`.
    Removal returns the order object rather than the line."

    Design: Corner/calculations/draft_line_deletion_reprices_the_aggregate_rollup
    """
    world = draft_order_with_one_reefer_line_and_one_malt_line
    brewer_headers = make_brewer_headers(world["brewer"]["id"])
    before = get_order(world["order"]["id"], brewer_headers)
    assert before["line_count"] == 2, (
        f"the order starts with two lines, got {before['line_count']}")
    assert before["requires_cold_chain"] is True, (
        f"the Citra line demands reefer, got {before['requires_cold_chain']}")

    reduced = validate_success(api.remove_order_line(
        world["order"]["id"], world["hop_line"]["id"], brewer_headers))
    assert reduced["line_count"] == 1, (
        f"only the malt line survives, got {reduced['line_count']}")
    assert reduced["chargeable_lbs"] == 1000, (
        "the poundage is re-derived over the survivor rather than decremented, "
        f"got {reduced['chargeable_lbs']}")
    assert reduced["subtotal_cents"] == 68500, (
        f"1000 lbs at 68.50 is 68500, got {reduced['subtotal_cents']}")
    assert reduced["requires_cold_chain"] is False, (
        "losing the only cold-chain line flips the order back to ambient, got "
        f"{reduced['requires_cold_chain']}")
    assert reduced["freight_cents"] == 0, (
        f"the fee engine has not run yet, got {reduced['freight_cents']}")
    assert reduced["pallet_break_fee_cents"] == 0, (
        f"nor has the pallet-break fee, got {reduced['pallet_break_fee_cents']}")
    assert reduced["small_order_surcharge_cents"] == 0, (
        f"nor the small-order surcharge, got {reduced['small_order_surcharge_cents']}")
    assert reduced["total_cents"] == 0, (
        f"a DRAFT order carries no total, got {reduced['total_cents']}")
    assert reduced["fulfillment_status"] == "DRAFT", (
        f"the order is still a draft, got {reduced['fulfillment_status']}")

    removed = validate_success(api.get_order_line(world["hop_line"]["id"],
                                                 brewer_headers))
    assert removed["status"] == "REMOVED", (
        f"the deleted line is terminal, got {removed['status']}")
    survivor = validate_success(api.get_order_line(world["malt_line"]["id"],
                                                   brewer_headers))
    assert survivor["status"] == "OPEN", (
        f"the untouched line is still open, got {survivor['status']}")

    variety = validate_success(api.get_hop_variety(world["variety"]["id"],
                                                   AM_HEADERS))
    assert variety["available_spot_lbs"] == 20000, (
        "a DRAFT line never held spot stock to release, got "
        f"{variety['available_spot_lbs']}")

    confirmed = confirm_order(world["order"]["id"], world["brewer"]["id"])
    assert confirmed["freight_cents"] == 25000, (
        "the 12-cent rating is lifted to the TIER_1 minimum with no reefer "
        f"surcharge, got {confirmed['freight_cents']}")
    assert confirmed["total_cents"] == 105500, (
        "68500 plus 25000 freight, 4500 pallet break and 7500 surcharge = 105500, "
        f"got {confirmed['total_cents']}")


def test_an_order_stripped_of_every_line_cannot_be_confirmed(
        api, draft_order_with_one_reefer_line_and_one_malt_line):
    """Deleting both lines leaves nothing to price, so confirmation is refused.

    PRD §3.8: "The order must hold at least one line in `OPEN` or `TRIMMED`,
    otherwise `ERR_ORDER_HAS_NO_LINES`."

    Design: Corner/calculations/draft_line_deletion_reprices_the_aggregate_rollup
    """
    world = draft_order_with_one_reefer_line_and_one_malt_line
    brewer_headers = make_brewer_headers(world["brewer"]["id"])
    validate_success(api.remove_order_line(world["order"]["id"],
                                           world["hop_line"]["id"],
                                           brewer_headers))
    emptied = validate_success(api.remove_order_line(world["order"]["id"],
                                                     world["malt_line"]["id"],
                                                     brewer_headers))
    assert emptied["line_count"] == 0, (
        f"the roll-up now covers nothing, got {emptied['line_count']}")
    assert emptied["chargeable_lbs"] == 0, (
        f"no poundage remains, got {emptied['chargeable_lbs']}")
    assert emptied["subtotal_cents"] == 0, (
        f"nor any money, got {emptied['subtotal_cents']}")
    assert emptied["requires_cold_chain"] is False, (
        f"an empty order needs no reefer, got {emptied['requires_cold_chain']}")

    refused = api.confirm_order(world["order"]["id"], brewer_headers)
    validate_error(refused, "ERR_ORDER_HAS_NO_LINES", expected_status=422)
    still_draft = get_order(world["order"]["id"], brewer_headers)
    assert still_draft["fulfillment_status"] == "DRAFT", (
        f"the refusal leaves the order in DRAFT, got {still_draft['fulfillment_status']}")


@pytest.fixture
def shipped_malt_order_of_one_hundred_fifty_thousand():
    """A SHIPPED ambient malt order, so ar_balance_cents reads exactly 150025."""
    pin_clock()
    brewer = create_brewer(name="Payment Ledger Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    product = create_malt_product()
    lot = create_released_lot(product["id"], quantity_lbs=5000,
                             lot_code="LOT-PM-1", **CONFORMING_SHEET)
    order = create_order(brewer["id"],
                        requested_ship_date="2026-09-05T00:00:00Z",
                        purchase_order_ref="PO-PM")
    add_malt_line(order["id"], brewer["id"], lot["id"], 1650)
    order = confirm_order(order["id"], brewer["id"])
    approve_credit(order["id"], note="within limit")
    pick_order(order["id"])
    order = ship_order(order["id"])
    return {"brewer": brewer, "product": product, "lot": lot, "order": order}


def test_a_receipt_one_cent_over_the_balance_is_refused(
        api, shipped_malt_order_of_one_hundred_fifty_thousand):
    """150026 against a 150025 receivable is refused and the ledger is untouched.

    PRD §3.1: "A receipt whose `amount_cents` exceeds the brewery's current
    `ar_balance_cents` is refused with `ERR_PAYMENT_EXCEEDS_BALANCE`; a receipt
    that exactly clears the balance is accepted. The balance can therefore never be
    driven negative by a payment"

    Design: Corner/calculations/payment_clears_the_receivable_and_cannot_overdraw_it
    """
    world = shipped_malt_order_of_one_hundred_fifty_thousand
    assert world["order"]["total_cents"] == 150025, (
        "113025 plus 25000 freight, 4500 pallet break and 7500 surcharge = 150025, "
        f"got {world['order']['total_cents']}")
    invoiced = get_brewer(world["brewer"]["id"])
    assert invoiced["ar_balance_cents"] == 150025, (
        f"shipping books the invoice, got {invoiced['ar_balance_cents']}")
    assert invoiced["open_order_exposure_cents"] == 0, (
        "a SHIPPED order has left the open-order bucket, got "
        f"{invoiced['open_order_exposure_cents']}")

    refused = api.post_payment(world["brewer"]["id"],
                              {"amount_cents": 150026,
                               "received_at": "2026-08-01T00:00:00Z",
                               "reference": "cheque 4416"}, CM_HEADERS)
    validate_error(refused, "ERR_PAYMENT_EXCEEDS_BALANCE", expected_status=422)

    after = get_brewer(world["brewer"]["id"])
    assert after["ar_balance_cents"] == 150025, (
        "the refused receipt leaves the receivable alone rather than driving it "
        f"to -1, got {after['ar_balance_cents']}")
    assert after["credit_exposure_cents"] == 150025, (
        f"and leaves the exposure alone, got {after['credit_exposure_cents']}")


def test_a_receipt_that_exactly_clears_the_balance_is_accepted(
        api, shipped_malt_order_of_one_hundred_fifty_thousand):
    """150025 drives the receivable to 0 and leaves the shipped order untouched.

    PRD §3.1: "a receipt that exactly clears the balance is accepted"

    PRD §3.1: "Every accepted receipt re-runs the credit posture, which is the
    normal route by which a brewery is lifted from `HOLD` back to `WATCH` or
    `GOOD_STANDING`."

    Design: Corner/calculations/payment_clears_the_receivable_and_cannot_overdraw_it
    """
    world = shipped_malt_order_of_one_hundred_fifty_thousand
    paid = validate_success(api.post_payment(
        world["brewer"]["id"],
        {"amount_cents": 150025, "received_at": "2026-08-01T00:00:00Z",
         "reference": "cheque 4417"}, CM_HEADERS))
    assert paid["ar_balance_cents"] == 0, (
        f"the receipt clears the receivable exactly, got {paid['ar_balance_cents']}")
    assert paid["credit_status"] == "GOOD_STANDING", (
        f"a cleared ledger is in good standing, got {paid['credit_status']}")
    assert paid["credit_exposure_cents"] == 0, (
        f"no exposure remains, got {paid['credit_exposure_cents']}")
    assert paid["credit_utilization_pct"] == pytest.approx(0.00, abs=0.005), (
        f"an empty ledger is 0.00 percent used, got {paid['credit_utilization_pct']}")

    order = get_order(world["order"]["id"], make_brewer_headers(world["brewer"]["id"]))
    assert order["fulfillment_status"] == "SHIPPED", (
        f"the payment does not move the order, got {order['fulfillment_status']}")
    assert order["invoiced_at"].startswith("2026-08-01T00:00:00"), (
        f"nor rewrite its invoice stamp, got {order['invoiced_at']}")
    assert order["total_cents"] == 150025, (
        f"nor its total, got {order['total_cents']}")
