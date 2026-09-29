"""Corner coverage for read-your-writes immediacy across the run pipeline.

Every derived figure and every cross-entity side effect is final in the request that
caused it: the charge arithmetic and the plant's glass ledger, the cure index and the
emission masses, the produced coverage and the finished-goods lot it mints, and the
packaging economics struck when the SKU is defined.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_client import InsulationApiClient
from test_helpers.assertions import assert_close, assert_field_equals
from test_helpers.constants import SKU_PL_A, ZONES_470
from test_helpers.test_users import plant_operator_headers

# A formaldehyde-free chemistry: 0 ppm free formaldehyde, 3.2 g/kg VOC, curing from
# 420 F with a 150 s minimum dwell.
FREE_BINDER = {
    "code": "BF-FREE-1",
    "formaldehyde_free": True,
    "formaldehyde_ppm": 0,
    "voc_g_per_kg": 3.2,
    "min_cure_temp_f": 420.0,
    "min_dwell_s": 150.0,
    "loi_target_pct": 4.5,
}

RUN_START = "2026-08-03T06:00:00Z"
RUN_END = "2026-08-03T14:00:00Z"

TARGET_PULL_KG = 9200.0
CULLET_MASS_KG = 1500.00

# 9200 / 0.92 = 10000.00 kg charged; ceiling 10000.00 * 0.30 = 3000.00 kg, so the single
# 1500.00 kg batch is taken whole; virgin glass is the residual 8500.00 kg and the run's
# fraction is 1500 / 10000 = 0.1500.
EXPECTED_TOTAL_CHARGE_KG = 10000.00
EXPECTED_ALLOWED_CULLET_KG = 3000.00
EXPECTED_VIRGIN_KG = 8500.00
EXPECTED_CULLET_FRACTION = 0.1500

# 120 ft / 40 fpm * 60 = 180.00 s dwell; ratio 180 / 150 = 1.2; margin
# (470 - 420) / 60 = 0.8333...; index 1.2 * 1.8333... / 2 * 100 = 110.00.
CURE_MEASUREMENTS = {
    "avg_zone_temp_f": 470.0,
    "line_speed_fpm": 40.0,
    "binder_applied_kg": 900.0,
}
EXPECTED_DWELL_S = 180.00
EXPECTED_CURE_INDEX = 110.00
EXPECTED_FORMALDEHYDE_KG = 0.0000  # 900 * 0 / 1e6
EXPECTED_VOC_KG = 2.8800  # 900 * 3.2 / 1000

BAGS_PRODUCED = 120
EXPECTED_PRODUCED_SQFT = 10560.00  # 120 bags * the SKU's bag_sqft of 88.0

# PL-A packaging economics: excess ratio 6.0 - 4.0 = 2.0 costing 2 * 5.0 = 10.00 points
# from 100, unfaced so no further penalty, floor 80.00 not reached; bale 21.0 / 6.0;
# cube-bound truck floor(3800 / 3.500) = 1085 against payload floor(19500 / 12.5) = 1560;
# freight 2450.00 / (1085 * 88.0); shortfall 95.0 - 90.00 charged at 0.0012 per point.
EXPECTED_RECOVERED_THICKNESS_PCT = 90.00
EXPECTED_COMPRESSED_BALE_VOLUME_FT3 = 3.500
EXPECTED_BALES_PER_TRUCK = 1085
EXPECTED_FREIGHT_PER_SQFT = 0.025660
EXPECTED_PENALTY_PER_SQFT = 0.006000
EXPECTED_NET_LANDED_PER_SQFT = 0.031660


def _scenario(client: InsulationApiClient) -> Dict[str, Any]:
    """Reference data, one STAGED 1500.00 kg cullet batch and one SCHEDULED run of PL-A."""
    ctx = fx.base_setup(
        client,
        binder_overrides=dict(FREE_BINDER),
        sku_overrides=dict(SKU_PL_A),
    )
    fx.set_clock(client, RUN_START)
    ctx["batch"] = fx.stage_cullet(client, ctx["plant_id"], CULLET_MASS_KG)
    ctx["batch_id"] = ctx["batch"]["id"]
    run = fx.schedule_run(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        scheduled_start=RUN_START,
        scheduled_end=RUN_END,
        line_index=1,
        target_pull_kg=TARGET_PULL_KG,
        zone_setpoints_f=list(ZONES_470),
    )
    ctx["run"] = run
    ctx["run_id"] = run["id"]
    return ctx


def test_the_charge_arithmetic_and_ledger_are_final_in_the_charging_request(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "In the same request the plant's ledger moves: `cullet_charged_kg_ytd`
    increases by the mass charged, `total_charge_kg_ytd` increases by the run's total
    charge, `cullet_fraction_ytd` is recomputed as the charged-cullet accumulator divided
    by the total-charge accumulator rounded half up to four decimal places, and
    `cullet_on_hand_kg` is recomputed as received less charged less rejected."

    Design: Corner/consistency_model/every_derived_field_and_side_effect_is_visible_in_the_same_request
    """
    ctx = _scenario(client)

    response = client.start_melt(
        ctx["run_id"], [ctx["batch_id"]], plant_operator_headers(ctx["plant_id"])
    )
    melting = validate_success(response)

    # The POST body itself already carries the finished arithmetic - no follow-up read.
    assert_field_equals(melting, "run_status", "MELTING")
    assert_close(melting["total_charge_kg"], EXPECTED_TOTAL_CHARGE_KG, 2, "total_charge_kg")
    assert_close(
        melting["allowed_cullet_kg"], EXPECTED_ALLOWED_CULLET_KG, 2, "allowed_cullet_kg"
    )
    assert_close(melting["cullet_charged_kg"], CULLET_MASS_KG, 2, "cullet_charged_kg")
    assert_close(melting["virgin_batch_kg"], EXPECTED_VIRGIN_KG, 2, "virgin_batch_kg")
    assert_close(
        melting["cullet_fraction"], EXPECTED_CULLET_FRACTION, 4, "cullet_fraction"
    )

    # The plant read issued immediately afterwards shows the ledger already moved.
    plant = fx.get_plant(client, ctx["plant_id"])
    assert_close(
        plant["cullet_charged_kg_ytd"], CULLET_MASS_KG, 2, "cullet_charged_kg_ytd"
    )
    assert_close(
        plant["total_charge_kg_ytd"], EXPECTED_TOTAL_CHARGE_KG, 2, "total_charge_kg_ytd"
    )
    assert_close(
        plant["cullet_fraction_ytd"], EXPECTED_CULLET_FRACTION, 4, "cullet_fraction_ytd"
    )
    # 1500.00 received, 1500.00 charged, nothing rejected.
    assert_close(plant["cullet_on_hand_kg"], 0.00, 2, "cullet_on_hand_kg")

    # The cross-entity side effect was committed with the parent write, not queued.
    batch = fx.get_cullet_batch(client, ctx["batch_id"])
    assert_field_equals(batch, "status", "CHARGED")
    assert_field_equals(batch, "charged_run_id", ctx["run_id"])

    # Reading the run back changes nothing: the write settled at once.
    reread = fx.get_run(client, ctx["run_id"])
    for field in (
        "run_status",
        "total_charge_kg",
        "allowed_cullet_kg",
        "cullet_charged_kg",
        "virgin_batch_kg",
        "cullet_fraction",
    ):
        assert reread[field] == melting[field], (
            f"{field} changed between the charging response and the next read: "
            f"{melting[field]!r} then {reread[field]!r}"
        )


def test_cure_and_packaging_responses_already_carry_every_derived_figure(
    client: InsulationApiClient,
) -> None:
    """PRD 2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."

    Design: Corner/consistency_model/every_derived_field_and_side_effect_is_visible_in_the_same_request
    """
    ctx = _scenario(client)
    fx.start_melt(client, ctx["plant_id"], ctx["run_id"], [ctx["batch_id"]])

    curing = validate_success(
        client.start_cure(
            ctx["run_id"],
            dict(CURE_MEASUREMENTS),
            plant_operator_headers(ctx["plant_id"]),
        )
    )
    assert_field_equals(curing, "run_status", "CURING")
    assert_close(curing["dwell_s"], EXPECTED_DWELL_S, 2, "dwell_s")
    assert_close(curing["cure_index"], EXPECTED_CURE_INDEX, 2, "cure_index")
    assert_close(
        curing["formaldehyde_kg"], EXPECTED_FORMALDEHYDE_KG, 4, "formaldehyde_kg"
    )
    assert_close(curing["voc_kg"], EXPECTED_VOC_KG, 4, "voc_kg")

    packaged = validate_success(
        client.package_run(
            ctx["run_id"], BAGS_PRODUCED, plant_operator_headers(ctx["plant_id"])
        )
    )
    assert_field_equals(packaged, "run_status", "PACKAGED")
    assert_close(packaged["produced_sqft"], EXPECTED_PRODUCED_SQFT, 2, "produced_sqft")

    # The final read agrees with what the two POST responses already reported.
    reread = fx.get_run(client, ctx["run_id"])
    for field in (
        "run_status",
        "dwell_s",
        "cure_index",
        "binder_applied_kg",
        "formaldehyde_kg",
        "voc_kg",
        "produced_sqft",
    ):
        assert reread[field] == packaged[field], (
            f"{field} changed between the packaging response and the next read: "
            f"{packaged[field]!r} then {reread[field]!r}"
        )


def test_the_lot_minted_by_packaging_is_listable_in_the_very_next_request(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "That lot appears in no response body; it is found only by filtering the lot
    collection on the run, as described in 2.3."

    Design: Corner/consistency_model/every_derived_field_and_side_effect_is_visible_in_the_same_request
    """
    ctx = _scenario(client)
    fx.start_melt(client, ctx["plant_id"], ctx["run_id"], [ctx["batch_id"]])
    fx.start_cure(client, ctx["plant_id"], ctx["run_id"], **CURE_MEASUREMENTS)
    packaged = fx.package_run(
        client, ctx["plant_id"], ctx["run_id"], bags_produced=BAGS_PRODUCED
    )

    lots, _meta = validate_paginated(
        client.list_inventory_lots(
            plant_operator_headers(ctx["plant_id"]),
            {"production_run_id": ctx["run_id"], "limit": 100},
        )
    )
    assert len(lots) == 1, f"expected the minted lot to be listable at once, got {len(lots)}"
    lot = lots[0]
    assert_field_equals(lot, "status", "AVAILABLE")
    assert_field_equals(lot, "bags", BAGS_PRODUCED)
    assert_close(lot["produced_sqft"], EXPECTED_PRODUCED_SQFT, 2, "produced_sqft")
    assert_close(lot["allocated_sqft"], 0.00, 2, "allocated_sqft")
    assert_close(lot["available_sqft"], EXPECTED_PRODUCED_SQFT, 2, "available_sqft")
    assert lot["produced_sqft"] == packaged["produced_sqft"], (
        "the lot's coverage must match the run's produced_sqft in the same instant"
    )


def test_packaging_economics_are_finished_inside_the_sku_creation_response(
    client: InsulationApiClient,
) -> None:
    """PRD 3.3: "Packaging is where freight cost and installed performance pull against each
    other, and the API prices both sides on every SKU write."

    Design: Corner/consistency_model/every_derived_field_and_side_effect_is_visible_in_the_same_request
    """
    ctx = fx.base_setup(
        client,
        binder_overrides=dict(FREE_BINDER),
        sku_overrides=dict(SKU_PL_A),
    )
    created = ctx["sku"]

    assert_close(
        created["recovered_thickness_pct"],
        EXPECTED_RECOVERED_THICKNESS_PCT,
        2,
        "recovered_thickness_pct",
    )
    assert_close(
        created["compressed_bale_volume_ft3"],
        EXPECTED_COMPRESSED_BALE_VOLUME_FT3,
        3,
        "compressed_bale_volume_ft3",
    )
    assert_field_equals(created, "bales_per_truck", EXPECTED_BALES_PER_TRUCK)
    assert_close(
        created["freight_cost_per_sqft"], EXPECTED_FREIGHT_PER_SQFT, 6, "freight_cost_per_sqft"
    )
    assert_close(
        created["recovery_penalty_per_sqft"],
        EXPECTED_PENALTY_PER_SQFT,
        6,
        "recovery_penalty_per_sqft",
    )
    assert_close(
        created["net_landed_cost_per_sqft"],
        EXPECTED_NET_LANDED_PER_SQFT,
        6,
        "net_landed_cost_per_sqft",
    )

    # Re-reading the SKU changes nothing: the five steps ran inside the creating write.
    reread = fx.get_product_line(client, ctx["sku_id"])
    for field in (
        "recovered_thickness_pct",
        "compressed_bale_volume_ft3",
        "bales_per_truck",
        "freight_cost_per_sqft",
        "recovery_penalty_per_sqft",
        "net_landed_cost_per_sqft",
    ):
        assert reread[field] == created[field], (
            f"{field} changed between the creating response and the next read: "
            f"{created[field]!r} then {reread[field]!r}"
        )
