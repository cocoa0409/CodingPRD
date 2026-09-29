"""Arithmetic: weightings, bounded fees, pinned rounding order and truncation.

Mass-weighted blends over two feedstock classes, the input set that a release
shrinks, the pretreatment adder that must be paid exactly once, the fee floor and
cap that bound the linear term, the tie that must round up, the daily feed rate
that must be rounded before it is multiplied, catalyst decay per kilotonne, the
governing sample chosen by `sampled_at`, and a credit count that is truncated.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_INVALID_LOT_STATE
from test_helpers.assertions import (
    assert_activity_index,
    assert_fields_null,
    assert_mass,
    assert_money,
    assert_one_decimal,
)
from test_helpers.test_users import (
    ANALYST_HEADERS,
    OFFICER_A_HEADERS,
    OPERATOR_HEADERS,
    TRADER_HEADERS,
)
from test_helpers.types import (
    ALLOC_RELEASED,
    ALLOC_RESERVED,
    BLOCK_DRAFT,
    CERT_UNCERTIFIED,
    CHARGE_ACTIVE,
    DISPOSITION_PASS,
    DISPOSITION_PRETREAT,
    DIST_IN_TANK,
    DIST_SHIPPED,
    FEEDSTOCK_TALLOW,
    FEEDSTOCK_UCO,
    LOT_ACCEPTED,
    LOT_PRETREAT_REQUIRED,
    LOT_PRETREATED,
    OUTCOME_NONE,
    PRODUCT_RENEWABLE_DIESEL,
    PRODUCT_SAF,
    PROGRAM_RFS,
    RUN_COMPLETED,
    TIER_HEAVY,
    TIER_LIGHT,
    TIER_NONE,
    UNIT_IDLE,
)


def _two_class_campaign(api):
    """A five-day campaign plus two ACCEPTED 200.000 MT lots of different classes.

    The UCO lot is attested at 32.50 and the TALLOW lot at 24.90; both pass their
    quality test at tier NONE, so nothing but the mass weighting can move the
    blend. Returns {"run", "uco_lot", "tallow_lot"}.
    """
    plant = fx.commissioned_unit(api)
    supplier = fx.verified_supplier(api, feedstock_types=[FEEDSTOCK_UCO, FEEDSTOCK_TALLOW])
    uco_lot = fx.accepted_lot(
        api,
        supplier["id"],
        feedstock_type=FEEDSTOCK_UCO,
        mass_mt=200.000,
        attested_ci_gco2e_per_mj=32.50,
        purchase_price_usd_per_mt=900.00,
    )
    tallow_lot = fx.accepted_lot(
        api,
        supplier["id"],
        feedstock_type=FEEDSTOCK_TALLOW,
        mass_mt=200.000,
        attested_ci_gco2e_per_mj=24.90,
        purchase_price_usd_per_mt=880.00,
    )
    run = fx.make_run(
        api, plant["unit"]["id"], plant["charge"]["id"], target_saf_share_pct=0.00
    )
    return {"run": run, "uco_lot": uco_lot, "tallow_lot": tallow_lot}


def test_the_second_allocation_reweights_both_the_blend_and_the_hydrogen(api):
    """PRD §3.5: "Add those products together without rounding anything along the way, divide by
    the total counted `mass_mt`, and round the single final quotient half up to 2 decimal
    places."
    PRD §3.5: "Second, a mass-weighted hydrogen intensity: for each counted line multiply its
    `mass_mt` by the hydrogen intensity of its lot's `feedstock_type` — 32.0 kilograms of
    hydrogen per metric tonne for `UCO`, 30.0 for `TALLOW`, 34.0 for `DCO`, 38.0 for
    `SOYBEAN_OIL` and 36.0 for `CANOLA_OIL` — sum those products, and divide by the total
    counted mass, keeping this quotient unrounded."

    Design: Corner/calculations/blend_ci_weighted_average_over_two_accepted_lots
    """
    ctx = _two_class_campaign(api)

    fx.allocate(api, ctx["run"]["id"], ctx["uco_lot"]["id"], 200.000)
    one_line = validate_success(api.get_processing_run(ctx["run"]["id"], OPERATOR_HEADERS))
    assert one_line["blend_ci_gco2e_per_mj"] == 32.50, f"got {one_line['blend_ci_gco2e_per_mj']}"
    assert_one_decimal(one_line["required_h2_kg_per_day"], 1280.0, "required_h2_kg_per_day")

    second = validate_success(
        api.create_allocation(
            ctx["run"]["id"],
            f.allocation_payload(ctx["tallow_lot"]["id"], 200.000, one_line["version"]),
            TRADER_HEADERS,
        ),
        201,
    )
    assert_mass(second["mass_mt"], 200.000)

    both = validate_success(api.get_processing_run(ctx["run"]["id"], OPERATOR_HEADERS))
    assert_mass(both["reserved_mass_mt"], 400.000, "reserved_mass_mt")
    assert both["blend_ci_gco2e_per_mj"] == 28.70, f"got {both['blend_ci_gco2e_per_mj']}"
    assert_one_decimal(both["required_h2_kg_per_day"], 2480.0, "required_h2_kg_per_day")
    assert both["version"] == 3, f"got {both['version']}"


def test_releasing_one_line_drops_it_out_of_the_blend_input_set(api):
    """PRD §3.5: "The counted lines are the campaign's allocations whose status is `RESERVED` or
    `CONSUMED`; `RELEASED` lines are excluded, which is exactly why a release moves the blend."
    PRD §3.5: "A campaign's `required_h2_kg_per_day` is derived from the same counted lines —
    allocations at `RESERVED` or `CONSUMED` — and is null when there are none, because nothing
    is being fed."

    Design: Corner/calculations/blend_ci_excludes_released_allocations_from_the_input_set
    """
    ctx = _two_class_campaign(api)
    fx.allocate(api, ctx["run"]["id"], ctx["uco_lot"]["id"], 200.000)
    tallow_line = fx.allocate(api, ctx["run"]["id"], ctx["tallow_lot"]["id"], 200.000)

    released = validate_success(api.release_allocation(tallow_line["id"], TRADER_HEADERS))
    assert released["status"] == ALLOC_RELEASED, f"got {released['status']}"

    run = validate_success(api.get_processing_run(ctx["run"]["id"], OPERATOR_HEADERS))
    assert_mass(run["reserved_mass_mt"], 200.000, "reserved_mass_mt")
    assert run["blend_ci_gco2e_per_mj"] == 32.50, f"got {run['blend_ci_gco2e_per_mj']}"
    assert_one_decimal(run["required_h2_kg_per_day"], 1280.0, "required_h2_kg_per_day")

    lot = validate_success(api.get_feedstock_lot(ctx["tallow_lot"]["id"], TRADER_HEADERS))
    assert_mass(lot["allocated_mass_mt"], 0.000, "allocated_mass_mt")
    assert_mass(lot["remaining_mass_mt"], 200.000, "remaining_mass_mt")

    _, meta = validate_paginated(
        api.list_run_allocations(
            ctx["run"]["id"], OPERATOR_HEADERS, {"status": ALLOC_RESERVED}
        )
    )
    assert meta["total_count"] == 1, f"one line still counts, got {meta['total_count']}"


def test_the_pretreat_adder_reaches_the_blend_only_through_the_child_lot(api):
    """PRD §3.2: "Its `attested_ci_gco2e_per_mj` is the source lot's attested carbon intensity
    plus a pretreatment carbon adder determined by the *source* lot's tier — 1.50 grams of CO2
    equivalent per megajoule for a `LIGHT` source and 4.00 for a `HEAVY` source, and 0.00 for a
    source at `NONE`."
    PRD §3.2: "And its `purchase_price_usd_per_mt` rolls the pretreatment fee into the cost
    basis — it is the source lot's `mass_mt` multiplied by the source lot's
    `purchase_price_usd_per_mt`, plus the source lot's `pretreatment_fee_usd`, all divided by
    `output_mass_mt`, rounded half up to 2 decimal places."
    PRD §3.5: "Recall from §3.2 that a pretreated child lot sits at tier `NONE` and already
    carries its adder inside its attested figure, so the adder is never applied twice to the
    same material."

    Design: Corner/calculations/blend_ci_adds_the_pretreat_adder_once_through_the_child_lot
    """
    plant = fx.commissioned_unit(api)
    supplier = fx.verified_supplier(api, feedstock_types=[FEEDSTOCK_TALLOW])
    source = fx.tested_lot(
        api,
        supplier["id"],
        test={"ffa_pct": 6.00},
        feedstock_type=FEEDSTOCK_TALLOW,
        mass_mt=300.000,
        attested_ci_gco2e_per_mj=21.40,
        purchase_price_usd_per_mt=880.00,
    )
    assert source["status"] == LOT_PRETREAT_REQUIRED, f"got {source['status']}"
    assert_money(source["pretreatment_fee_usd"], 17313.75, "pretreatment_fee_usd")
    run = fx.make_run(
        api, plant["unit"]["id"], plant["charge"]["id"], target_saf_share_pct=0.00
    )

    child = validate_success(
        api.create_pretreatment(source["id"], f.pretreatment_payload(280.000), ANALYST_HEADERS),
        201,
    )

    spent = validate_success(api.get_feedstock_lot(source["id"], TRADER_HEADERS))
    assert spent["status"] == LOT_PRETREATED, f"got {spent['status']}"
    assert_mass(spent["pretreatment_consumed_mt"], 300.000, "pretreatment_consumed_mt")
    assert_mass(spent["pretreatment_loss_mt"], 20.000, "pretreatment_loss_mt")
    assert_mass(spent["remaining_mass_mt"], 0.000, "remaining_mass_mt")

    assert child["status"] == LOT_ACCEPTED, f"got {child['status']}"
    assert child["source_lot_id"] == source["id"]
    assert_mass(child["mass_mt"], 280.000)
    assert child["pretreatment_tier"] == TIER_NONE
    assert child["attested_ci_gco2e_per_mj"] == 25.40, (
        f"21.40 plus the HEAVY adder of 4.00, got {child['attested_ci_gco2e_per_mj']}"
    )
    assert_money(child["purchase_price_usd_per_mt"], 1004.69, "purchase_price_usd_per_mt")

    fx.allocate(api, run["id"], child["id"], 280.000)
    blended = validate_success(api.get_processing_run(run["id"], OPERATOR_HEADERS))
    assert blended["blend_ci_gco2e_per_mj"] == 25.40, (
        f"29.40 would mean the adder was paid twice, got {blended['blend_ci_gco2e_per_mj']}"
    )
    assert_one_decimal(blended["required_h2_kg_per_day"], 1680.0, "required_h2_kg_per_day")


def test_a_tiny_light_lot_pays_the_floor_rather_than_its_linear_term(api):
    """PRD §3.2: "That linear term is then raised to a floor of 250.00 US dollars if it falls
    below it, capped at 45000.00 US dollars if it exceeds that, and finally rounded half up to 2
    decimal places."
    PRD §3.2: "`ffa_tier_index` is 2 when `ffa_pct` is at least 5.00, otherwise 1 when it is at
    least 2.00, otherwise 0."

    Design: Corner/calculations/pretreatment_fee_floor_overrides_the_linear_term
    """
    supplier = fx.make_supplier(api, feedstock_types=[FEEDSTOCK_UCO])
    lot = fx.make_lot(api, supplier["id"], mass_mt=10.000)

    row = fx.add_quality_test(api, lot["id"], lot["version"], ffa_pct=2.00)
    assert row["ffa_tier_index"] == 1, f"2.00 is exactly the boundary, got {row['ffa_tier_index']}"
    assert row["tier"] == TIER_LIGHT, f"got {row['tier']}"
    assert row["disposition"] == DISPOSITION_PRETREAT, f"got {row['disposition']}"

    governed = validate_success(api.get_feedstock_lot(lot["id"], TRADER_HEADERS))
    assert governed["status"] == LOT_PRETREAT_REQUIRED, f"got {governed['status']}"
    assert governed["pretreatment_tier"] == TIER_LIGHT
    assert_money(governed["pretreatment_fee_usd"], 250.00, "pretreatment_fee_usd")


def test_a_thousand_tonne_heavy_lot_pays_the_cap_rather_than_its_linear_term(api):
    """PRD §3.2: "Otherwise the linear term is the per-tonne base rate for the governing tier —
    18.50 US dollars per metric tonne for `LIGHT` and 42.75 for `HEAVY` — multiplied by the
    lot's `mass_mt`, multiplied by a feedstock-type multiplier of 1.20 for `UCO`, 1.35 for
    `TALLOW`, 1.10 for `DCO`, and 1.00 for both `SOYBEAN_OIL` and `CANOLA_OIL`."
    PRD §3.2: "The floor is applied before the cap, and both bound the linear term rather than
    the rounded output."

    Design: Corner/calculations/pretreatment_fee_cap_bounds_the_linear_term
    """
    supplier = fx.make_supplier(api, feedstock_types=[FEEDSTOCK_TALLOW])
    lot = fx.make_lot(
        api,
        supplier["id"],
        feedstock_type=FEEDSTOCK_TALLOW,
        mass_mt=1000.000,
        attested_ci_gco2e_per_mj=21.40,
        purchase_price_usd_per_mt=880.00,
    )

    row = fx.add_quality_test(api, lot["id"], lot["version"], ffa_pct=6.00)
    assert row["tier"] == TIER_HEAVY, f"got {row['tier']}"
    assert row["disposition"] == DISPOSITION_PRETREAT, f"got {row['disposition']}"

    governed = validate_success(api.get_feedstock_lot(lot["id"], TRADER_HEADERS))
    assert governed["pretreatment_tier"] == TIER_HEAVY
    assert_money(governed["pretreatment_fee_usd"], 45000.00, "pretreatment_fee_usd")


def test_the_gallon_conversion_rounds_the_exact_half_gallon_upward(api):
    """PRD §3.7: "Its `volume_gal` is that `mass_mt` multiplied by a per-product conversion factor
    — 308.0 gallons per metric tonne for `RENEWABLE_DIESEL` and 322.0 for `SAF` — rounded half up
    to 1 decimal place."
    PRD §3.7: "Both dimensions of a new batch start at their initial values: `cert_status` is
    `UNCERTIFIED` and `distribution_status` is `IN_TANK`, with `astm_annex`, `freeze_point_c`,
    `cert_reject_reason` and `offtaker_name` all null."

    Design: Corner/calculations/product_volume_conversion_rounds_half_up_at_the_exact_tie
    """
    ctx = fx.completed_campaign(api, measured_rd_mt=290.123, measured_saf_mt=30.125)
    assert ctx["run"]["status"] == RUN_COMPLETED, f"got {ctx['run']['status']}"

    saf = fx.find_batch(api, ctx["run"]["id"], PRODUCT_SAF)
    diesel = fx.find_batch(api, ctx["run"]["id"], PRODUCT_RENEWABLE_DIESEL)

    assert_one_decimal(saf["volume_gal"], 9700.3, "volume_gal")
    assert_one_decimal(diesel["volume_gal"], 89357.9, "volume_gal")
    for batch in (saf, diesel):
        assert batch["cert_status"] == CERT_UNCERTIFIED, f"got {batch['cert_status']}"
        assert batch["distribution_status"] == DIST_IN_TANK, f"got {batch['distribution_status']}"
        assert_fields_null(batch, "astm_annex", "freeze_point_c", "offtaker_name")

    assert_mass(ctx["run"]["final_yield_pct"], 80.062, "final_yield_pct")
    assert_mass(ctx["run"]["yield_variance_pct"], -1.938, "yield_variance_pct")
    assert ctx["run"]["yield_variance_flag"] is False


def test_the_daily_feed_rate_is_rounded_before_it_multiplies_the_intensity(api):
    """PRD §3.5: "Third, the daily feed rate: the total counted mass divided by the campaign's
    `run_days`, and this one **is rounded half up to 3 decimal places before it is used**."
    PRD §3.5: "Rounding the daily feed rate only at the end produces a different kilogram figure
    and is wrong."

    Design: Corner/calculations/hydrogen_requirement_pins_daily_feed_rounding_before_multiplying
    """
    plant = fx.commissioned_unit(api)
    supplier = fx.verified_supplier(api, feedstock_types=[FEEDSTOCK_UCO])
    lot = fx.accepted_lot(api, supplier["id"], mass_mt=500.000)
    run = fx.make_run(
        api,
        plant["unit"]["id"],
        plant["charge"]["id"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-04T00:00:00Z",
        target_saf_share_pct=0.00,
    )
    assert run["run_days"] == 3, f"got {run['run_days']}"

    fx.allocate(api, run["id"], lot["id"], 100.007)

    fed = validate_success(api.get_processing_run(run["id"], OPERATOR_HEADERS))
    assert_mass(fed["reserved_mass_mt"], 100.007, "reserved_mass_mt")
    assert_one_decimal(fed["required_h2_kg_per_day"], 1066.8, "required_h2_kg_per_day")
    assert fed["blend_ci_gco2e_per_mj"] == 32.50, f"got {fed['blend_ci_gco2e_per_mj']}"


def test_one_completed_campaign_decays_the_charge_by_its_own_throughput(api):
    """PRD §3.3: "The `activity_index` is then 1.0000 reduced by 0.0125 for every thousand metric
    tonnes of cumulative throughput — that is, 1.0000 less the product of 0.0125 and the
    cumulative throughput divided by 1000 — with the result held at a floor of 0.6000 if the
    arithmetic would take it lower, and rounded half up to 4 decimal places."
    PRD §3.6: "`yield_variance_pct` is `final_yield_pct` less `provisional_yield_pct`, rounded to
    3 decimal places, and `yield_variance_flag` is set when the absolute value of that variance
    is strictly greater than the 2.000 percentage-point tolerance."

    Design: Corner/calculations/catalyst_activity_decays_per_kilotonne_of_throughput
    """
    ctx = fx.completed_campaign(api)

    assert_mass(ctx["run"]["provisional_yield_pct"], 82.000, "provisional_yield_pct")
    assert_mass(ctx["run"]["final_yield_pct"], 80.000, "final_yield_pct")
    assert_mass(ctx["run"]["yield_variance_pct"], -2.000, "yield_variance_pct")
    assert ctx["run"]["yield_variance_flag"] is False, "exactly 2.000 is inside the tolerance"

    charges, meta = validate_paginated(
        api.list_catalyst_charges(
            ctx["unit"]["id"], OPERATOR_HEADERS, {"status": CHARGE_ACTIVE}
        )
    )
    assert meta["total_count"] == 1, f"got {meta['total_count']}"
    charge = charges[0]
    assert charge["id"] == ctx["charge"]["id"]
    assert_mass(charge["cumulative_throughput_mt"], 400.000, "cumulative_throughput_mt")
    assert_activity_index(charge["activity_index"], 0.9950)
    assert charge["status"] == CHARGE_ACTIVE, f"got {charge['status']}"

    unit = validate_success(api.get_unit(ctx["unit"]["id"], OPERATOR_HEADERS))
    assert unit["requires_turnaround"] is False
    assert unit["status"] == UNIT_IDLE, f"got {unit['status']}"


def test_a_back_filled_older_sample_does_not_overturn_the_governing_test(api):
    """PRD §3.2: "Which test governs the lot at any later moment is a separate question, answered
    by the **governing test** rule: among all tests on the lot, the governing test is the one
    with the greatest `sampled_at`; if two or more tie on `sampled_at`, the one with the greatest
    `created_at` wins."
    PRD §3.2: "An earlier `sampled_at` never governs merely because it was appended later — a
    laboratory back-filling yesterday's sample does not overturn today's disposition."
    PRD §3.2: "Accepting a lot in any other status — a `RECEIVED` lot that has never been tested,
    for instance — is refused with `ERR_INVALID_LOT_STATE`."

    Design: Corner/calculations/governing_quality_test_ignores_a_later_filed_older_sample
    """
    supplier = fx.make_supplier(api, feedstock_types=[FEEDSTOCK_TALLOW])
    lot = fx.make_lot(
        api,
        supplier["id"],
        feedstock_type=FEEDSTOCK_TALLOW,
        mass_mt=300.000,
        attested_ci_gco2e_per_mj=21.40,
        purchase_price_usd_per_mt=880.00,
    )
    fx.add_quality_test(
        api, lot["id"], lot["version"], ffa_pct=6.00, sampled_at="2026-08-02T00:00:00Z"
    )
    heavy = validate_success(api.get_feedstock_lot(lot["id"], TRADER_HEADERS))
    assert heavy["pretreatment_tier"] == TIER_HEAVY, f"got {heavy['pretreatment_tier']}"

    late_filing = validate_success(
        api.create_quality_test(
            lot["id"],
            f.quality_test_payload(
                heavy["version"], ffa_pct=1.00, sampled_at="2026-08-01T00:00:00Z"
            ),
            ANALYST_HEADERS,
        ),
        201,
    )
    assert late_filing["disposition"] == DISPOSITION_PASS, f"got {late_filing['disposition']}"
    assert late_filing["tier"] == TIER_NONE, f"got {late_filing['tier']}"

    unmoved = validate_success(api.get_feedstock_lot(lot["id"], TRADER_HEADERS))
    assert unmoved["status"] == LOT_PRETREAT_REQUIRED, f"got {unmoved['status']}"
    assert unmoved["pretreatment_tier"] == TIER_HEAVY
    assert_money(unmoved["pretreatment_fee_usd"], 17313.75, "pretreatment_fee_usd")
    assert unmoved["version"] == 3, f"the append still bumped the lot, got {unmoved['version']}"

    rows, meta = validate_paginated(api.list_quality_tests(lot["id"], ANALYST_HEADERS))
    assert meta["total_count"] == 2, f"got {meta['total_count']}"
    assert len(rows) == 2

    validate_error(api.accept_lot(lot["id"], ANALYST_HEADERS), ERR_INVALID_LOT_STATE)


def test_the_rin_count_is_truncated_and_leaves_the_lcfs_fields_at_zero(api):
    """PRD §3.8: "For an `RFS` block, `provisional_rin_credits` is the batch's `volume_gal`
    multiplied by a renewable-identification-number equivalence factor of 1.7 for
    `RENEWABLE_DIESEL` or 1.6 for `SAF`, with the fractional part discarded to give a whole
    number."
    PRD §3.8: "Credit counts are always truncated downward, never rounded."
    PRD §3.8: "Its `provisional_ci_gco2e_per_mj` is frozen at creation as the producing
    campaign's `blend_ci_gco2e_per_mj` plus a process carbon adder of 8.75 grams of CO2
    equivalent per megajoule, rounded half up to 2 decimal places."

    Design: Corner/calculations/rin_credit_quantity_floors_and_never_rounds
    """
    ctx = fx.reconciled_campaign(
        api, measured_rd_mt=320.123, measured_saf_mt=0.000, target_saf_share_pct=0.00
    )
    batch = fx.find_batch(api, ctx["run"]["id"], PRODUCT_RENEWABLE_DIESEL)
    assert_one_decimal(batch["volume_gal"], 98597.9, "volume_gal")

    shipped = fx.ship_batch(api, batch["id"], offtaker_name="Chevron Renewable Fuels")
    assert shipped["distribution_status"] == DIST_SHIPPED, f"got {shipped['distribution_status']}"

    pathway = fx.registered_pathway(api, ctx["unit"]["id"], program=PROGRAM_RFS)

    block = validate_success(
        api.create_credit_block(
            f.credit_block_payload(batch["id"], pathway["id"]), OFFICER_A_HEADERS
        ),
        201,
    )

    assert block["program"] == PROGRAM_RFS, f"got {block['program']}"
    assert block["status"] == BLOCK_DRAFT, f"got {block['status']}"
    assert block["provisional_ci_gco2e_per_mj"] == 41.25, (
        f"32.50 plus the 8.75 process adder, got {block['provisional_ci_gco2e_per_mj']}"
    )
    assert block["provisional_rin_credits"] == 167616, (
        f"167616.43 must be truncated, got {block['provisional_rin_credits']}"
    )
    assert_mass(block["provisional_credits_mtco2e"], 0.000, "provisional_credits_mtco2e")
    assert_mass(block["retired_credits_mtco2e"], 0.000, "retired_credits_mtco2e")
    assert block["verification_outcome"] == OUTCOME_NONE, f"got {block['verification_outcome']}"
    assert_fields_null(block, "signed_off_by_user_id")
