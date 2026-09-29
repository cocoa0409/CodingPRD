"""Calculation corners: the arithmetic behind every derived figure on a row.

Corner design / calculations.
"""

from typing import Any, Dict, List

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import InsulationApiClient
from test_helpers.api_errors import ApiErrors
from test_helpers.assertions import (
    assert_area,
    assert_bale_volume,
    assert_close,
    assert_emissions,
    assert_field_equals,
    assert_mass,
    assert_per_sqft_cost,
    assert_ratio,
)
from test_helpers.constants import SKU_PL_A, SKU_PL_B, ZONES_470, ZONES_480
from test_helpers.test_users import (
    CERTIFICATION_OFFICER_USER_ID,
    certification_officer_headers,
    channel_manager_headers,
    plant_operator_headers,
    quality_engineer_headers,
)

# A phenolic chemistry whose cure minima match the 470 F / 40 fpm recipe used by
# the cure and emissions scenarios below.
PHENOLIC_420_150 = {"min_cure_temp_f": 420.0, "min_dwell_s": 150.0}

# 12.40 fails the 12.70 conformance floor of a PER_SPECIMEN program while the
# 12.73 lot mean clears it, so one specimen set drives both derate bases.
DERATE_SPECIMENS = [12.40, 12.90, 12.90]


def _reference(client: InsulationApiClient) -> Dict[str, Any]:
    """Program RCERT-PS, plant NWK and a CERTIFIED phenolic formulation."""
    fx.reset_clock(client)
    program = fx.create_per_specimen_program(client)
    plant = fx.create_plant(client)
    binder = fx.create_certified_binder(client)
    return {
        "program_id": program["id"],
        "plant": plant,
        "plant_id": plant["id"],
        "binder_id": binder["id"],
        "operator": plant_operator_headers(plant["id"]),
    }


# ---------------------------------------------------------------------------
# cure_index_hits_both_of_its_caps_on_two_runs_of_the_same_oven
# ---------------------------------------------------------------------------


def _two_cures_one_oven(client: InsulationApiClient) -> Dict[str, Any]:
    """Two runs on the 120 ft oven: 470 F at 40 fpm, then 490 F at 32 fpm."""
    ctx = fx.base_setup(
        client,
        binder_overrides=dict(PHENOLIC_420_150),
        sku_overrides=dict(SKU_PL_A),
    )
    ctx["run_in_band"] = fx.run_to_curing(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        clock="2026-08-02T06:00:00Z",
        cure_overrides={
            "avg_zone_temp_f": 470.0,
            "line_speed_fpm": 40.0,
            "binder_applied_kg": 900.0,
        },
        scheduled_start="2026-08-02T06:00:00Z",
        scheduled_end="2026-08-02T14:00:00Z",
        zone_setpoints_f=list(ZONES_470),
    )
    ctx["run_saturated"] = fx.run_to_curing(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        clock="2026-08-03T06:00:00Z",
        cure_overrides={
            "avg_zone_temp_f": 490.0,
            "line_speed_fpm": 32.0,
            "binder_applied_kg": 900.0,
        },
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-03T14:00:00Z",
        zone_setpoints_f=list(ZONES_480),
    )
    return ctx


def test_cure_index_inside_both_caps_scales_with_dwell_and_temperature(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "`cure_index` is then the dwell ratio multiplied by one plus the
    temperature margin, divided by two, multiplied by 100, rounded half up to two
    decimal places - so a line running at exactly the binder's minimum dwell and
    exactly its minimum temperature scores 50.00, and a fully saturated margin at
    the dwell cap scores 125.00."

    Design: Corner/calculations/cure_index_hits_both_of_its_caps_on_two_runs_of_the_same_oven
    """
    ctx = _two_cures_one_oven(client)
    run = ctx["run_in_band"]

    # 120 ft / 40 fpm * 60 = 180.00 s, a dwell ratio of 1.2 under the 1.25 cap, and
    # a margin of (470 - 420) / 60 = 0.8333... inside the closed 0..1 range.
    assert_close(run["dwell_s"], 180.00, 2, "dwell_s")
    assert_close(run["cure_index"], 110.00, 2, "cure_index")
    assert_field_equals(run, "run_status", "CURING")


def test_cure_index_saturates_at_the_dwell_cap_and_the_full_temperature_margin(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "The dwell ratio is `dwell_s` divided by the formulation's
    `min_dwell_s`, capped at 1.25 so that no amount of extra dwell can compensate
    without limit."

    Design: Corner/calculations/cure_index_hits_both_of_its_caps_on_two_runs_of_the_same_oven
    """
    ctx = _two_cures_one_oven(client)
    slow = ctx["run_saturated"]

    # 120 ft / 32 fpm * 60 = 225.00 s is a raw ratio of 1.5 clamped to 1.25, and
    # 490 F is 70 degrees over the minimum so the margin clamps to exactly 1.
    assert_close(slow["dwell_s"], 225.00, 2, "dwell_s")
    assert_close(slow["cure_index"], 125.00, 2, "cure_index")
    # The same oven length drove both runs; only the line speed and temperature moved.
    assert_close(ctx["plant"]["oven_length_ft"], 120.0, 1, "oven_length_ft")
    assert_close(ctx["run_in_band"]["cure_index"], 110.00, 2, "cure_index")


# ---------------------------------------------------------------------------
# per_run_emission_masses_are_carried_at_four_decimal_places
# ---------------------------------------------------------------------------


def _two_binder_charges(client: InsulationApiClient) -> Dict[str, Any]:
    """A 250 ppm / 4.1 g/kg chemistry sprayed at 900.0 kg, then at 137.7 kg."""
    ctx = fx.base_setup(
        client,
        binder_overrides=dict(PHENOLIC_420_150),
        sku_overrides=dict(SKU_PL_A),
    )
    ctx["heavy"] = fx.run_to_curing(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        clock="2026-08-02T06:00:00Z",
        cure_overrides={
            "avg_zone_temp_f": 470.0,
            "line_speed_fpm": 40.0,
            "binder_applied_kg": 900.0,
        },
        scheduled_start="2026-08-02T06:00:00Z",
        scheduled_end="2026-08-02T14:00:00Z",
        zone_setpoints_f=list(ZONES_470),
    )
    ctx["light"] = fx.run_to_curing(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        clock="2026-08-03T06:00:00Z",
        cure_overrides={
            "avg_zone_temp_f": 470.0,
            "line_speed_fpm": 40.0,
            "binder_applied_kg": 137.7,
        },
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-03T14:00:00Z",
        zone_setpoints_f=list(ZONES_470),
    )
    return ctx


def test_booked_emission_masses_quantize_to_four_places_in_both_directions(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "`formaldehyde_kg` is `binder_applied_kg` multiplied by the
    formulation's `formaldehyde_ppm` divided by one million, rounded half up to four
    decimal places - parts per million converted to a mass fraction. `voc_kg` is
    `binder_applied_kg` multiplied by the formulation's `voc_g_per_kg` divided by one
    thousand, rounded half up to four decimal places, converting grams per kilogram
    into kilograms."

    Design: Corner/calculations/per_run_emission_masses_are_carried_at_four_decimal_places
    """
    ctx = _two_binder_charges(client)

    # 900.0 * 250 / 1e6 = 0.2250 and 900.0 * 4.1 / 1000 = 3.6900, both exact at 4 dp.
    assert_emissions(ctx["heavy"]["formaldehyde_kg"], 0.2250, "formaldehyde_kg")
    assert_emissions(ctx["heavy"]["voc_kg"], 3.6900, "voc_kg")
    assert_close(ctx["heavy"]["binder_applied_kg"], 900.0, 2, "binder_applied_kg")

    # 137.7 * 250 / 1e6 = 0.034425 rounds down to 0.0344 while
    # 137.7 * 4.1 / 1000 = 0.564570 rounds up to 0.5646.
    assert_emissions(ctx["light"]["formaldehyde_kg"], 0.0344, "formaldehyde_kg")
    assert_emissions(ctx["light"]["voc_kg"], 0.5646, "voc_kg")
    assert_close(ctx["light"]["binder_applied_kg"], 137.7, 2, "binder_applied_kg")


def test_permit_period_totals_sum_the_stored_four_place_run_masses(
    client: InsulationApiClient,
) -> None:
    """PRD 3.9: "`reported_formaldehyde_kg` is the sum of `formaldehyde_kg` over that
    set, quantized to four decimal places, and `reported_voc_kg` is the sum of
    `voc_kg` over the same set, quantized to four decimal places."

    Design: Corner/calculations/per_run_emission_masses_are_carried_at_four_decimal_places
    """
    ctx = _two_binder_charges(client)

    fx.set_clock(client, "2026-08-05T00:00:00Z")
    plant = fx.file_emissions_report(
        client, ctx["plant_id"], "2026-08-01T00:00:00Z", "2026-08-04T00:00:00Z"
    )

    # 0.2250 + 0.0344 = 0.2594 kg and 3.6900 + 0.5646 = 4.2546 kg.
    assert_emissions(
        plant["reported_formaldehyde_kg"], 0.2594, "reported_formaldehyde_kg"
    )
    assert_emissions(plant["reported_voc_kg"], 4.2546, "reported_voc_kg")
    # 0.2594 is strictly above the 0.200 kg allowance; 4.2546 is under the 12.0 kg one.
    assert_field_equals(plant, "emissions_status", "EXCEEDANCE")


# ---------------------------------------------------------------------------
# packaging_economics_applies_every_declared_truck_and_recovery_constant
# ---------------------------------------------------------------------------


def test_heavy_bale_lets_the_payload_limit_beat_the_cube(
    client: InsulationApiClient,
) -> None:
    """PRD 3.3: "A trailer holds 3800 cubic feet and carries 19500 kilograms of
    payload. The volume-bound count is 3800 divided by `compressed_bale_volume_ft3`,
    truncated down to a whole number of bales; the payload-bound count is 19500
    divided by `bale_mass_kg`, likewise truncated down."

    Design: Corner/calculations/packaging_economics_applies_every_declared_truck_and_recovery_constant
    """
    ctx = _reference(client)

    sku = fx.create_product_line(
        client,
        ctx["plant_id"],
        ctx["binder_id"],
        ctx["program_id"],
        facing_type="UNFACED",
        compression_ratio=6.0,
        bale_volume_ft3=21.0,
        bale_mass_kg=26.0,
        bag_sqft=88.0,
    )

    # 21.0 / 6.0 = 3.500 ft3 puts 1085 bales under the cube, but 19500 / 26.0 lands
    # on exactly 750 bales, so the scale is what binds.
    assert_bale_volume(sku["compressed_bale_volume_ft3"], 3.500)
    assert_field_equals(sku, "bales_per_truck", 750)
    # 2450.00 / (750 * 88.0 sqft) = 0.037121 and 95.0 - 90.00 = 5.00 points of
    # shortfall at 0.0012 USD per point.
    assert_per_sqft_cost(sku["freight_cost_per_sqft"], 0.037121, "freight_cost_per_sqft")
    assert_close(sku["recovered_thickness_pct"], 90.00, 2, "recovered_thickness_pct")
    assert_per_sqft_cost(
        sku["recovery_penalty_per_sqft"], 0.006000, "recovery_penalty_per_sqft"
    )
    assert_per_sqft_cost(
        sku["net_landed_cost_per_sqft"], 0.043121, "net_landed_cost_per_sqft"
    )


def test_facing_penalty_alone_still_beats_the_declared_recovery_minimum(
    client: InsulationApiClient,
) -> None:
    """PRD 3.3: "The declared recovery minimum is 95.0 percent. The shortfall is 95.0
    less `recovered_thickness_pct`, or zero when recovery meets or beats the minimum,
    and only that shortfall is charged back."

    Design: Corner/calculations/packaging_economics_applies_every_declared_truck_and_recovery_constant
    """
    ctx = _reference(client)

    sku = fx.create_product_line(
        client,
        ctx["plant_id"],
        ctx["binder_id"],
        ctx["program_id"],
        facing_type="FSK",
        compression_ratio=4.0,
        bale_volume_ft3=21.0,
        bale_mass_kg=12.5,
        bag_sqft=88.0,
    )

    # A ratio of exactly 4.0 is free of compression loss, so only the flat 2.0
    # facing points come off: 100 - 0 - 2.0 = 98.00, still above the 95.0 minimum.
    assert_close(sku["recovered_thickness_pct"], 98.00, 2, "recovered_thickness_pct")
    assert_per_sqft_cost(
        sku["recovery_penalty_per_sqft"], 0.000000, "recovery_penalty_per_sqft"
    )
    # 21.0 / 4.0 = 5.250 ft3 caps the trailer at 723 bales against 1560 by mass.
    assert_bale_volume(sku["compressed_bale_volume_ft3"], 5.250)
    assert_field_equals(sku, "bales_per_truck", 723)
    assert_per_sqft_cost(sku["freight_cost_per_sqft"], 0.038507, "freight_cost_per_sqft")
    assert_per_sqft_cost(
        sku["net_landed_cost_per_sqft"], 0.038507, "net_landed_cost_per_sqft"
    )


def test_fractional_compression_excess_is_charged_at_five_points_per_ratio_point(
    client: InsulationApiClient,
) -> None:
    """PRD 3.3: "The excess is the compression ratio less 4.0, or zero if the ratio is
    at or below 4.0. From a nominal 100 percent the system subtracts that excess
    multiplied by 5.0, rounded half up to two decimal places, and then subtracts a
    further flat 2.0 percentage points whenever the SKU's facing is anything other
    than `UNFACED`."

    Design: Corner/calculations/packaging_economics_applies_every_declared_truck_and_recovery_constant
    """
    ctx = _reference(client)

    sku = fx.create_product_line(
        client,
        ctx["plant_id"],
        ctx["binder_id"],
        ctx["program_id"],
        facing_type="UNFACED",
        compression_ratio=7.4,
        bale_volume_ft3=21.0,
        bale_mass_kg=12.5,
        bag_sqft=88.0,
    )

    # An excess of 3.4 ratio points costs 17.00 recovery points, landing on 83.00 -
    # above the 80.00 floor, so the floor does not bite and 12.00 points are charged.
    assert_close(sku["recovered_thickness_pct"], 83.00, 2, "recovered_thickness_pct")
    assert_per_sqft_cost(
        sku["recovery_penalty_per_sqft"], 0.014400, "recovery_penalty_per_sqft"
    )
    # 21.0 / 7.4 = 2.838 ft3 gives 1338 bales by cube against 1560 by mass.
    assert_bale_volume(sku["compressed_bale_volume_ft3"], 2.838)
    assert_field_equals(sku, "bales_per_truck", 1338)
    assert_per_sqft_cost(sku["freight_cost_per_sqft"], 0.020808, "freight_cost_per_sqft")
    assert_per_sqft_cost(
        sku["net_landed_cost_per_sqft"], 0.035208, "net_landed_cost_per_sqft"
    )


# ---------------------------------------------------------------------------
# cullet_fraction_exactly_at_the_restrict_level_freezes_new_staging
# ---------------------------------------------------------------------------


def _charge_with_cullet(
    client: InsulationApiClient, masses: List[float]
) -> Dict[str, Any]:
    """Stage the given batches, then charge them into a 9200 kg pull target."""
    ctx = fx.base_setup(client, sku_overrides=dict(SKU_PL_A))
    batches = fx.stage_cullet_batches(client, ctx["plant_id"], masses)
    ctx["batches"] = batches
    ctx["version_before"] = fx.plant_version(client, ctx["plant_id"])
    ctx["melting"] = fx.run_to_melting(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        [batch["id"] for batch in batches],
    )
    return ctx


def test_year_to_date_fraction_landing_on_the_restrict_level_tightens_the_posture(
    client: InsulationApiClient,
) -> None:
    """PRD 3.1: "`OPEN` becomes `RESTRICTED` automatically, evaluated by the server at
    the end of a furnace charge, whenever the freshly recomputed `cullet_fraction_ytd`
    stands **at or above** `cullet_restrict_fraction` - equality trips the restriction,
    it does not have to be exceeded. That transition sets `posture_reason` to
    `CULLET_FRACTION_AT_RESTRICT_LEVEL` and increments the plant's `version` by one."

    Design: Corner/calculations/cullet_fraction_exactly_at_the_restrict_level_freezes_new_staging
    """
    ctx = _charge_with_cullet(client, [1500.0, 1300.0])

    # 9200 / 0.92 = 10000.00 kg of charge, and 2800.00 kg of it is cullet, so the
    # ledger lands on exactly the 0.28 restrict level.
    assert_mass(ctx["melting"]["total_charge_kg"], 10000.00, "total_charge_kg")
    assert_mass(ctx["melting"]["cullet_charged_kg"], 2800.00, "cullet_charged_kg")
    assert_ratio(ctx["melting"]["cullet_fraction"], 0.2800, "cullet_fraction")

    plant = fx.get_plant(client, ctx["plant_id"])
    assert_ratio(plant["cullet_fraction_ytd"], 0.2800, "cullet_fraction_ytd")
    assert_close(plant["cullet_restrict_fraction"], 0.28, 2, "cullet_restrict_fraction")
    assert_field_equals(plant, "melt_posture", "RESTRICTED")
    assert_field_equals(plant, "posture_reason", "CULLET_FRACTION_AT_RESTRICT_LEVEL")
    assert plant["version"] > ctx["version_before"], (
        f"posture change must move the plant version past {ctx['version_before']}"
    )


def test_a_fraction_a_hundredth_under_the_restrict_level_leaves_the_plant_open(
    client: InsulationApiClient,
) -> None:
    """PRD 3.1: "whenever the freshly recomputed `cullet_fraction_ytd` stands **at or
    above** `cullet_restrict_fraction` - equality trips the restriction, it does not
    have to be exceeded."

    Design: Corner/calculations/cullet_fraction_exactly_at_the_restrict_level_freezes_new_staging
    """
    ctx = _charge_with_cullet(client, [1500.0, 1200.0])

    # 2700.00 of 10000.00 is 0.2700, one hundredth short of the 0.28 trip level.
    assert_mass(ctx["melting"]["cullet_charged_kg"], 2700.00, "cullet_charged_kg")
    assert_ratio(ctx["melting"]["cullet_fraction"], 0.2700, "cullet_fraction")

    plant = fx.get_plant(client, ctx["plant_id"])
    assert_ratio(plant["cullet_fraction_ytd"], 0.2700, "cullet_fraction_ytd")
    assert_field_equals(plant, "melt_posture", "OPEN")
    assert_field_equals(plant, "posture_reason", None)


def test_the_tightened_posture_turns_away_the_next_staged_batch(
    client: InsulationApiClient,
) -> None:
    """PRD 3.1: "A `RESTRICTED` posture is narrower: it blocks only the staging of new
    cullet, rejected with `ERR_MELT_POSTURE_RESTRICTED`, because no further recycled
    glass may enter the yard until an environmental review has cleared the plant back
    to `OPEN`."

    Design: Corner/calculations/cullet_fraction_exactly_at_the_restrict_level_freezes_new_staging
    """
    ctx = _charge_with_cullet(client, [1500.0, 1300.0])
    plant_id = ctx["plant_id"]

    response = client.create_cullet_batch(
        f.cullet_batch_payload(plant_id, 400.0, fx.plant_version(client, plant_id)),
        plant_operator_headers(plant_id),
    )

    validate_error(response, ApiErrors.MELT_POSTURE_RESTRICTED)
    plant = fx.get_plant(client, plant_id)
    # The refused stage adds nothing to the yard: 2800.00 received, all of it charged.
    assert_mass(plant["cullet_received_kg_ytd"], 2800.00, "cullet_received_kg_ytd")
    assert_mass(plant["cullet_on_hand_kg"], 0.00, "cullet_on_hand_kg")


# ---------------------------------------------------------------------------
# quarantined_supply_and_late_orders_are_filtered_out_of_the_waterfall
# ---------------------------------------------------------------------------


def test_a_quarantined_lot_leaves_the_waterfall_with_nothing_to_share(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "Supply is the set of lots whose `plant_id` and `product_line_id` match
    the cycle's and whose status is exactly `AVAILABLE`, taken in `created_at` ascending
    order - a quarantined or already fully-booked lot contributes nothing."

    PRD 3.8: "`allocatable_sqft` must be strictly greater than 0.00 or the proposal is
    refused with `ERR_NO_ALLOCATABLE_SUPPLY`"

    Design: Corner/calculations/quarantined_supply_and_late_orders_are_filtered_out_of_the_waterfall
    """
    ctx = fx.certified_sku_with_lot(client, sku_overrides=dict(SKU_PL_A))
    fx.quarantine_lot(client, ctx["lot_id"])
    fx.place_order(client, ctx["sku_id"], 4400.0)
    cycle = fx.open_cycle(client, ctx["plant_id"], ctx["sku_id"])

    response = client.propose_cycle(cycle["id"], channel_manager_headers())

    validate_error(response, ApiErrors.NO_ALLOCATABLE_SUPPLY)
    lot = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(lot, "status", "QUARANTINED")
    # The hold zeroes the coverage without ever rewriting produced_sqft.
    assert_area(lot["produced_sqft"], 10560.00, "produced_sqft")
    assert_area(lot["available_sqft"], 0.00, "available_sqft")
    refused = fx.get_cycle(client, cycle["id"])
    assert_field_equals(refused, "status", "OPEN")
    assert refused["total_available_sqft"] is None
    assert refused["shortage_ratio"] is None
    assert fx.lines_for_cycle(client, cycle["id"]) == []


def test_an_order_due_after_the_period_never_enters_the_demand_set(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "Demand is the set of orders whose `product_line_id` matches the
    cycle's, whose status is `SUBMITTED`, `PARTIAL` or `BACKORDERED`, whose
    `required_by` falls at or before the cycle's `period_end`, and whose remaining need
    - `requested_sqft` less `allocated_sqft` - is strictly greater than zero."

    PRD 3.8: "the demand set must be non-empty or the proposal is refused with
    `ERR_NO_ELIGIBLE_ORDERS` - an empty demand set is rejected rather than producing an
    empty proposal."

    Design: Corner/calculations/quarantined_supply_and_late_orders_are_filtered_out_of_the_waterfall
    """
    ctx = fx.certified_sku_with_lot(client, sku_overrides=dict(SKU_PL_A))
    late = fx.place_order(
        client, ctx["sku_id"], 4400.0, required_by="2026-09-15T00:00:00Z"
    )
    cycle = fx.open_cycle(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-31T00:00:00Z",
    )

    response = client.propose_cycle(cycle["id"], channel_manager_headers())

    validate_error(response, ApiErrors.NO_ELIGIBLE_ORDERS)
    # Supply was there all along - 10560.00 sqft available - so only the due date
    # kept the order out of the waterfall.
    lot = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(lot, "status", "AVAILABLE")
    assert_area(lot["available_sqft"], 10560.00, "available_sqft")
    untouched = fx.get_order(client, late["id"])
    assert_field_equals(untouched, "status", "SUBMITTED")
    assert_area(untouched["allocated_sqft"], 0.00, "allocated_sqft")
    assert fx.lines_for_cycle(client, cycle["id"]) == []


# ---------------------------------------------------------------------------
# derate_snaps_the_declared_value_down_to_the_step_below_the_worst_specimen
# ---------------------------------------------------------------------------


def _sku_awaiting_derate(
    client: InsulationApiClient, lot_mean: bool
) -> Dict[str, Any]:
    """An R13.0 SKU in the queue with one completed test over 12.40/12.90/12.90."""
    ctx = fx.base_setup(client, sku_overrides=dict(SKU_PL_A), lot_mean=lot_mean)
    fx.submit_sku(client, ctx["sku_id"])
    run = fx.run_to_packaged(client, ctx["plant_id"], ctx["sku_id"])
    ctx["run_id"] = run["id"]
    ctx["test"] = fx.completed_thermal_test(
        client, run["id"], ctx["sku_id"], ctx["program_id"], DERATE_SPECIMENS
    )
    return ctx


def test_per_specimen_derate_snaps_down_from_the_weakest_specimen(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "the basis value is that test's `min_r_value` when the program's
    `conformance_basis` is `PER_SPECIMEN` and its `mean_r_value` when the basis is
    `LOT_MEAN`; divide the basis value by a derate step of 0.5 and take the floor to a
    whole number of steps; multiply the step count back by 0.5 and quantize to two
    decimal places."

    Design: Corner/calculations/derate_snaps_the_declared_value_down_to_the_step_below_the_worst_specimen
    """
    ctx = _sku_awaiting_derate(client, lot_mean=False)
    assert_close(ctx["test"]["min_r_value"], 12.40, 2, "min_r_value")
    assert_field_equals(ctx["test"], "conformance_basis", "PER_SPECIMEN")
    assert_field_equals(ctx["test"], "conformance_verdict", "NONCONFORMING")

    derated = get_success_data(
        client.sku_certification_decision(
            ctx["sku_id"],
            f.sku_decision_payload("DERATE"),
            certification_officer_headers(),
        )
    )

    # 12.40 / 0.5 = 24.8 steps, floored to 24, back to 12.00 - the step below.
    assert_field_equals(derated, "certification_status", "DERATED")
    assert_close(derated["effective_declared_r_value"], 12.00, 2, "effective_declared_r_value")
    assert_close(derated["declared_r_value"], 13.0, 1, "declared_r_value")
    assert_field_equals(derated, "certified_by_user_id", CERTIFICATION_OFFICER_USER_ID)
    # The compromise branch does not count as a nonconformance against the SKU.
    assert_field_equals(derated, "nonconformance_count", 0)


def test_lot_mean_derate_snaps_down_from_the_mean_instead(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "The derated figure is snapped down onto a half-point grid: the basis
    value is that test's `min_r_value` when the program's `conformance_basis` is
    `PER_SPECIMEN` and its `mean_r_value` when the basis is `LOT_MEAN`"

    Design: Corner/calculations/derate_snaps_the_declared_value_down_to_the_step_below_the_worst_specimen
    """
    ctx = _sku_awaiting_derate(client, lot_mean=True)
    # The same three specimens: a 12.73 mean clears the 12.70 floor the 12.40 low fails.
    assert_close(ctx["test"]["mean_r_value"], 12.73, 2, "mean_r_value")
    assert_field_equals(ctx["test"], "conformance_basis", "LOT_MEAN")
    assert_field_equals(ctx["test"], "conformance_verdict", "CONFORMING")

    derated = get_success_data(
        client.sku_certification_decision(
            ctx["sku_id"],
            f.sku_decision_payload("DERATE"),
            certification_officer_headers(),
        )
    )

    # 12.73 / 0.5 = 25.46 steps, floored to 25, back to 12.50.
    assert_field_equals(derated, "certification_status", "DERATED")
    assert_close(derated["effective_declared_r_value"], 12.50, 2, "effective_declared_r_value")
    assert_close(derated["declared_r_value"], 13.0, 1, "declared_r_value")


# ---------------------------------------------------------------------------
# scrapping_a_lot_prefers_the_scale_reading_over_the_bale_bill_of_materials
# ---------------------------------------------------------------------------


def _quarantined_lot(
    client: InsulationApiClient, sku_overrides: Dict[str, Any], bags: int
) -> Dict[str, Any]:
    """A packaged lot of the given SKU, held under a manual quarantine."""
    ctx = fx.base_setup(client, sku_overrides=dict(sku_overrides))
    run = fx.run_to_packaged(
        client, ctx["plant_id"], ctx["sku_id"], bags_produced=bags
    )
    ctx["run_id"] = run["id"]
    lot = fx.lot_for_run(client, run["id"])
    ctx["lot_id"] = lot["id"]
    ctx["lot"] = lot
    fx.quarantine_lot(client, lot["id"])
    return ctx


def _scrap_lot(
    client: InsulationApiClient, lot_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.quarantine_lot(
            lot_id,
            f.quarantine_payload("SCRAP", **overrides),
            quality_engineer_headers(),
        )
    )


def _recovered_batch(
    client: InsulationApiClient, plant_id: str
) -> Dict[str, Any]:
    batches = fx.cullet_batches_for_plant(
        client, plant_id, source_type="QUARANTINE_SCRAP"
    )
    assert len(batches) == 1, f"expected exactly one recovered batch, got {batches}"
    return batches[0]


def test_a_scale_ticket_prices_the_recovered_glass_in_pounds(
    client: InsulationApiClient,
) -> None:
    """PRD 3.7: "The gross mass has two sources and the scale wins whenever it is
    present: if the payload carries a `weighed_scrap_lb` reading, the gross mass is that
    reading multiplied by a pound-to-kilogram factor of 0.45359237, quantized to two
    decimal places"

    Design: Corner/calculations/scrapping_a_lot_prefers_the_scale_reading_over_the_bale_bill_of_materials
    """
    ctx = _quarantined_lot(client, SKU_PL_A, bags=120)

    scrapped = _scrap_lot(client, ctx["lot_id"], weighed_scrap_lb=3000.0)

    assert_field_equals(scrapped, "status", "SCRAPPED")
    assert_area(scrapped["available_sqft"], 0.00, "available_sqft")
    # 3000.0 lb -> 1360.78 kg gross, UNFACED so all of it is glass, and the 0.85
    # recovery yield leaves 1156.66 kg.
    batch = _recovered_batch(client, ctx["plant_id"])
    assert_mass(batch["mass_kg"], 1156.66, "mass_kg")
    assert_field_equals(batch, "status", "STAGED")
    assert_field_equals(batch, "source_type", "QUARANTINE_SCRAP")
    assert_field_equals(batch, "source_run_id", ctx["run_id"])
    plant = fx.get_plant(client, ctx["plant_id"])
    assert_mass(plant["cullet_received_kg_ytd"], 1156.66, "cullet_received_kg_ytd")
    assert_mass(plant["cullet_on_hand_kg"], 1156.66, "cullet_on_hand_kg")


def test_without_a_ticket_the_bale_bill_of_materials_prices_the_same_lot(
    client: InsulationApiClient,
) -> None:
    """PRD 3.7: "otherwise it is taken from the bale bill of materials as the lot's
    `bags` multiplied by the SKU's `bale_mass_kg`, quantized to two decimal places. The
    two paths disagree by design, and the scale reading is authoritative."

    Design: Corner/calculations/scrapping_a_lot_prefers_the_scale_reading_over_the_bale_bill_of_materials
    """
    ctx = _quarantined_lot(client, SKU_PL_A, bags=120)
    assert_field_equals(ctx["lot"], "bags", 120)

    scrapped = _scrap_lot(client, ctx["lot_id"])

    assert_field_equals(scrapped, "status", "SCRAPPED")
    # 120 bags * 12.5 kg = 1500.00 kg gross, all of it glass, * 0.85 = 1275.00 kg -
    # far above the 1156.66 kg the same lot would recover on a 3000 lb ticket.
    batch = _recovered_batch(client, ctx["plant_id"])
    assert_mass(batch["mass_kg"], 1275.00, "mass_kg")
    assert_field_equals(batch, "source_run_id", ctx["run_id"])
    plant = fx.get_plant(client, ctx["plant_id"])
    assert_mass(plant["cullet_received_kg_ytd"], 1275.00, "cullet_received_kg_ytd")


def test_kraft_facing_is_deducted_before_the_recovery_yield(
    client: InsulationApiClient,
) -> None:
    """PRD 3.7: "Facing paper and foil are not glass and never reach the furnace, so an
    `UNFACED` SKU contributes its whole gross mass while any other `facing_type`
    contributes the gross mass multiplied by one minus a facing mass fraction of 0.08,
    quantized to two decimal places."

    Design: Corner/calculations/scrapping_a_lot_prefers_the_scale_reading_over_the_bale_bill_of_materials
    """
    ctx = _quarantined_lot(client, SKU_PL_B, bags=60)

    scrapped = _scrap_lot(client, ctx["lot_id"])

    assert_field_equals(scrapped, "status", "SCRAPPED")
    # 60 bags * 15.0 kg = 900.00 kg gross; KRAFT facing takes 8 percent off, leaving
    # 828.00 kg of glass, and 0.85 of that is 703.80 kg.
    batch = _recovered_batch(client, ctx["plant_id"])
    assert_mass(batch["mass_kg"], 703.80, "mass_kg")
    plant = fx.get_plant(client, ctx["plant_id"])
    assert_mass(plant["cullet_on_hand_kg"], 703.80, "cullet_on_hand_kg")


# ---------------------------------------------------------------------------
# contract_first_fills_the_top_tier_to_its_whole_bag_maximum_before_the_next
# ---------------------------------------------------------------------------


def _two_lot_demand(
    client: InsulationApiClient,
    basis: str,
    program_code: str = "RCERT-PS",
    site_code: str = "NWK",
    sku_code: str = "R13-15-UF",
) -> Dict[str, Any]:
    """10560.00 + 5280.00 sqft of supply against 8800/6160/4400 sqft of demand."""
    sku_overrides = dict(SKU_PL_A)
    sku_overrides["sku"] = sku_code
    ctx = fx.certified_sku_with_lot(
        client,
        bags_produced=120,
        program_overrides={"code": program_code},
        plant_overrides={"site_code": site_code},
        sku_overrides=sku_overrides,
    )
    second_run = fx.run_to_packaged(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        bags_produced=60,
        clock="2026-08-03T06:00:00Z",
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-03T14:00:00Z",
    )
    ctx["lot_a"] = fx.get_lot(client, ctx["lot_id"])
    ctx["lot_b"] = fx.lot_for_run(client, second_run["id"])
    ctx["contract"] = fx.place_order(
        client, ctx["sku_id"], 8800.0, priority_tier="CONTRACT"
    )
    ctx["program"] = fx.place_order(
        client, ctx["sku_id"], 6160.0, priority_tier="PROGRAM"
    )
    ctx["spot"] = fx.place_order(client, ctx["sku_id"], 4400.0, priority_tier="SPOT")
    ctx["cycle"] = fx.open_cycle(
        client, ctx["plant_id"], ctx["sku_id"], allocation_basis=basis
    )
    ctx["cycle_id"] = ctx["cycle"]["id"]
    return ctx


def _lines_by_lot(
    client: InsulationApiClient, order_id: str
) -> Dict[str, Dict[str, Any]]:
    return {
        line["inventory_lot_id"]: line
        for line in fx.lines_for_order(client, order_id)
    }


def test_contract_first_drains_the_pool_by_whole_bags_in_tier_order(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "Under `CONTRACT_FIRST`, the pool starts at `allocatable_sqft` and each
    order in sorted position takes as much as it can: the wanted figure is the lesser of
    the order's remaining need and the pool that is left, the bag count is the floor of
    that figure divided by the SKU's `bag_sqft`, and the grant is that whole bag count
    multiplied by `bag_sqft`, quantized to two decimal places, with the pool reduced by
    the grant."

    Design: Corner/calculations/contract_first_fills_the_top_tier_to_its_whole_bag_maximum_before_the_next
    """
    ctx = _two_lot_demand(client, "CONTRACT_FIRST")

    proposed = fx.propose_cycle(client, ctx["cycle_id"])

    assert_field_equals(proposed, "status", "PROPOSED")
    assert_field_equals(proposed, "peak_season", True)
    # 15840.00 available, 15 percent held back for August, 13464.00 to hand out.
    assert_area(proposed["total_available_sqft"], 15840.00, "total_available_sqft")
    assert_area(proposed["seasonal_reserve_sqft"], 2376.00, "seasonal_reserve_sqft")
    assert_area(proposed["allocatable_sqft"], 13464.00, "allocatable_sqft")
    assert_area(proposed["total_requested_sqft"], 19360.00, "total_requested_sqft")
    assert_ratio(proposed["shortage_ratio"], 0.6955, "shortage_ratio")
    assert_area(proposed["allocated_sqft"], 13464.00, "allocated_sqft")
    assert_area(proposed["unallocated_sqft"], 0.00, "unallocated_sqft")

    # CONTRACT takes its full 8800.00 (100 bags) off the first lot; PROGRAM takes the
    # 4664.00 (53 bags) that is left and spans both lots; SPOT sees nothing at all.
    lot_a_id = ctx["lot_a"]["id"]
    lot_b_id = ctx["lot_b"]["id"]
    contract_lines = _lines_by_lot(client, ctx["contract"]["id"])
    assert list(contract_lines) == [lot_a_id]
    assert_area(contract_lines[lot_a_id]["allocated_sqft"], 8800.00, "allocated_sqft")
    assert_field_equals(contract_lines[lot_a_id], "bags", 100)
    assert_field_equals(contract_lines[lot_a_id], "status", "PROPOSED")

    program_lines = _lines_by_lot(client, ctx["program"]["id"])
    assert sorted(program_lines) == sorted([lot_a_id, lot_b_id])
    assert_area(program_lines[lot_a_id]["allocated_sqft"], 1760.00, "allocated_sqft")
    assert_field_equals(program_lines[lot_a_id], "bags", 20)
    assert_area(program_lines[lot_b_id]["allocated_sqft"], 2904.00, "allocated_sqft")
    assert_field_equals(program_lines[lot_b_id], "bags", 33)

    assert fx.lines_for_order(client, ctx["spot"]["id"]) == []
    assert len(fx.lines_for_cycle(client, ctx["cycle_id"])) == 3


def test_committing_contract_first_books_the_starved_spot_order_as_backordered(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "its status is **derived** from the comparison: `ALLOCATED` when
    `allocated_sqft` equals `requested_sqft` exactly, `PARTIAL` when it is greater than
    zero but short of the request, and `BACKORDERED` when it is exactly 0.00 - an order
    that was eligible but could not be funded a whole bag."

    Design: Corner/calculations/contract_first_fills_the_top_tier_to_its_whole_bag_maximum_before_the_next
    """
    ctx = _two_lot_demand(client, "CONTRACT_FIRST")
    fx.propose_cycle(client, ctx["cycle_id"])

    fx.commit_cycle(client, ctx["cycle_id"])

    contract = fx.get_order(client, ctx["contract"]["id"])
    assert_area(contract["allocated_sqft"], 8800.00, "allocated_sqft")
    assert_close(contract["fill_rate_pct"], 100.00, 2, "fill_rate_pct")
    assert_field_equals(contract, "status", "ALLOCATED")

    # 4664.00 of 6160.00 is 75.71 percent once the whole-bag floor has bitten.
    program = fx.get_order(client, ctx["program"]["id"])
    assert_area(program["allocated_sqft"], 4664.00, "allocated_sqft")
    assert_close(program["fill_rate_pct"], 75.71, 2, "fill_rate_pct")
    assert_field_equals(program, "status", "PARTIAL")

    spot = fx.get_order(client, ctx["spot"]["id"])
    assert_area(spot["allocated_sqft"], 0.00, "allocated_sqft")
    assert_close(spot["fill_rate_pct"], 0.00, 2, "fill_rate_pct")
    assert_field_equals(spot, "status", "BACKORDERED")

    # The first lot is drawn to the square foot and flips itself to ALLOCATED; the
    # second keeps the 2376.00 sqft the seasonal reserve held back.
    lot_a = fx.get_lot(client, ctx["lot_a"]["id"])
    assert_area(lot_a["allocated_sqft"], 10560.00, "allocated_sqft")
    assert_area(lot_a["available_sqft"], 0.00, "available_sqft")
    assert_field_equals(lot_a, "status", "ALLOCATED")
    lot_b = fx.get_lot(client, ctx["lot_b"]["id"])
    assert_area(lot_b["allocated_sqft"], 2904.00, "allocated_sqft")
    assert_area(lot_b["available_sqft"], 2376.00, "available_sqft")
    assert_field_equals(lot_b, "status", "AVAILABLE")


# ---------------------------------------------------------------------------
# pro_rata_and_contract_first_diverge_on_identical_supply_and_demand
# ---------------------------------------------------------------------------


def test_pro_rata_shares_the_pool_in_two_whole_bag_passes(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "Pass one gives each order its proportional whole-bag share: multiply
    the order's remaining need by `shortage_ratio`, divide by `bag_sqft`, take the floor
    to whole bags, and multiply back to get the grant."

    PRD 3.8: "Pass two hands that remainder out **one bag at a time** in the same
    deterministic sorted order, sweeping the list repeatedly"

    Design: Corner/calculations/pro_rata_and_contract_first_diverge_on_identical_supply_and_demand
    """
    ctx = _two_lot_demand(client, "PRO_RATA")

    proposed = fx.propose_cycle(client, ctx["cycle_id"])

    assert_ratio(proposed["shortage_ratio"], 0.6955, "shortage_ratio")
    assert_area(proposed["allocatable_sqft"], 13464.00, "allocatable_sqft")
    # Pass one floors every share - 69, 48 and 34 bags for 13288.00 sqft - leaving
    # 176.00 sqft, exactly two bags, for pass two to hand to CONTRACT then PROGRAM.
    assert_area(proposed["allocated_sqft"], 13464.00, "allocated_sqft")
    assert_area(proposed["unallocated_sqft"], 0.00, "unallocated_sqft")

    lot_a_id = ctx["lot_a"]["id"]
    lot_b_id = ctx["lot_b"]["id"]

    contract_lines = _lines_by_lot(client, ctx["contract"]["id"])
    assert_area(contract_lines[lot_a_id]["allocated_sqft"], 6160.00, "allocated_sqft")
    assert_field_equals(contract_lines[lot_a_id], "bags", 70)

    program_lines = _lines_by_lot(client, ctx["program"]["id"])
    assert_area(program_lines[lot_a_id]["allocated_sqft"], 4312.00, "allocated_sqft")
    assert_field_equals(program_lines[lot_a_id], "bags", 49)

    # The SPOT grant of 2992.00 sqft drains the last bag of the first lot before
    # spilling onto the second.
    spot_lines = _lines_by_lot(client, ctx["spot"]["id"])
    assert_area(spot_lines[lot_a_id]["allocated_sqft"], 88.00, "allocated_sqft")
    assert_field_equals(spot_lines[lot_a_id], "bags", 1)
    assert_area(spot_lines[lot_b_id]["allocated_sqft"], 2904.00, "allocated_sqft")
    assert_field_equals(spot_lines[lot_b_id], "bags", 33)
    assert len(fx.lines_for_cycle(client, ctx["cycle_id"])) == 4


def test_only_the_basis_separates_a_starved_spot_order_from_a_funded_one(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "The two variants diverge sharply on identical inputs: `CONTRACT_FIRST`
    can leave a `SPOT` order at 0.00 and `BACKORDERED` while `PRO_RATA` funds it into
    `PARTIAL`, and the contract order's own grant differs between them. Only
    `allocation_basis` drives that difference."

    Design: Corner/calculations/pro_rata_and_contract_first_diverge_on_identical_supply_and_demand
    """
    strict = _two_lot_demand(client, "CONTRACT_FIRST")
    fx.propose_cycle(client, strict["cycle_id"])
    fx.commit_cycle(client, strict["cycle_id"])

    shared = _two_lot_demand(
        client,
        "PRO_RATA",
        program_code="RCERT-PR",
        site_code="NWKPR",
        sku_code="R13-15-UF-PR",
    )
    fx.propose_cycle(client, shared["cycle_id"])
    fx.commit_cycle(client, shared["cycle_id"])

    # Identical supply and demand: 15840.00 sqft over two lots against 8800/6160/4400.
    strict_spot = fx.get_order(client, strict["spot"]["id"])
    shared_spot = fx.get_order(client, shared["spot"]["id"])
    assert_area(strict_spot["allocated_sqft"], 0.00, "allocated_sqft")
    assert_field_equals(strict_spot, "status", "BACKORDERED")
    assert_area(shared_spot["allocated_sqft"], 2992.00, "allocated_sqft")
    assert_close(shared_spot["fill_rate_pct"], 68.00, 2, "fill_rate_pct")
    assert_field_equals(shared_spot, "status", "PARTIAL")

    # The contract order's own grant moves too: 8800.00 filled against 6160.00 shared.
    strict_contract = fx.get_order(client, strict["contract"]["id"])
    shared_contract = fx.get_order(client, shared["contract"]["id"])
    assert_area(strict_contract["allocated_sqft"], 8800.00, "allocated_sqft")
    assert_field_equals(strict_contract, "status", "ALLOCATED")
    assert_area(shared_contract["allocated_sqft"], 6160.00, "allocated_sqft")
    assert_close(shared_contract["fill_rate_pct"], 70.00, 2, "fill_rate_pct")
    assert_field_equals(shared_contract, "status", "PARTIAL")

    shared_program = fx.get_order(client, shared["program"]["id"])
    assert_area(shared_program["allocated_sqft"], 4312.00, "allocated_sqft")
    assert_close(shared_program["fill_rate_pct"], 70.00, 2, "fill_rate_pct")
    assert_field_equals(shared_program, "status", "PARTIAL")
