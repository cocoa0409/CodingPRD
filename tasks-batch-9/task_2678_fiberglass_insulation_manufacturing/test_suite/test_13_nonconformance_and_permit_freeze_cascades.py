"""Transitive cascades: one lab verdict walked down to a backordered order, and one
permit exceedance walked through the binder shelf into runs and cycles.

Queue A / transitive_cascade.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import InsulationApiClient
from test_helpers.assertions import assert_close, assert_field_equals
from test_helpers.constants import SKU_PL_A, SKU_PL_B, ZONES_470
from test_helpers.test_users import (
    CHANNEL_BUYER_USER_ID,
    QUALITY_ENGINEER_USER_ID_ALT,
    quality_engineer_headers,
)

FREE_BINDER = {
    "code": "BF-FREE-1",
    "formaldehyde_free": True,
    "formaldehyde_ppm": 0,
    "voc_g_per_kg": 3.2,
    "min_cure_temp_f": 420.0,
    "min_dwell_s": 150.0,
    "loi_target_pct": 4.5,
}

PHENOLIC_BINDER = {
    "code": "BF-PHEN-1",
    "formaldehyde_free": False,
    "formaldehyde_ppm": 250,
    "voc_g_per_kg": 4.1,
    "min_cure_temp_f": 430.0,
    "min_dwell_s": 160.0,
    "loi_target_pct": 5.0,
}

PL_D = dict(SKU_PL_B, sku="R19-23-KR-PH")

ZONES_490 = [490.0, 490.0, 490.0, 490.0]

CONFORMING_SPECIMENS = [13.10, 13.20, 12.90]
CONDEMNING_SPECIMENS = [12.40, 12.50, 12.60]
PL_D_SPECIMENS = [19.10, 19.20, 18.90]


def _committed_book(client: InsulationApiClient) -> Dict[str, Any]:
    """A CERTIFIED SKU with one packaged lot fully booked to one contract order.

    The certifying test is taken off a second run that never left the oven, so the
    lot-bearing run is still unsampled when the book is committed.
    """
    ctx = fx.base_setup(
        client,
        binder_overrides=dict(FREE_BINDER),
        sku_overrides=dict(SKU_PL_A),
    )
    fx.submit_sku(client, ctx["sku_id"])

    cert_run = fx.schedule_run(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-03T14:00:00Z",
        line_index=2,
        target_pull_kg=9200.0,
        zone_setpoints_f=list(ZONES_470),
    )
    fx.set_clock(client, "2026-08-03T06:00:00Z")
    fx.start_melt(client, ctx["plant_id"], cert_run["id"])
    fx.start_cure(
        client,
        ctx["plant_id"],
        cert_run["id"],
        avg_zone_temp_f=470.0,
        line_speed_fpm=40.0,
        binder_applied_kg=900.0,
    )
    fx.completed_thermal_test(
        client,
        cert_run["id"],
        ctx["sku_id"],
        ctx["program_id"],
        CONFORMING_SPECIMENS,
        window_start="2026-08-03T16:00:00Z",
        window_end="2026-08-03T20:00:00Z",
    )
    fx.certify_sku(client, ctx["sku_id"])

    run = fx.schedule_run(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-03T14:00:00Z",
        line_index=1,
        target_pull_kg=9200.0,
        zone_setpoints_f=list(ZONES_470),
    )
    fx.start_melt(client, ctx["plant_id"], run["id"])
    fx.start_cure(
        client,
        ctx["plant_id"],
        run["id"],
        avg_zone_temp_f=470.0,
        line_speed_fpm=40.0,
        binder_applied_kg=900.0,
    )
    run = fx.package_run(client, ctx["plant_id"], run["id"], bags_produced=120)
    lot = fx.lot_for_run(client, run["id"])

    order = fx.place_order(
        client,
        ctx["sku_id"],
        8800.0,
        channel_type="DISTRIBUTOR",
        priority_tier="CONTRACT",
        required_by="2026-08-31T00:00:00Z",
    )
    cycle = fx.open_cycle(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-31T23:59:59Z",
        allocation_basis="CONTRACT_FIRST",
    )
    fx.propose_cycle(client, cycle["id"])
    cycle = fx.commit_cycle(client, cycle["id"])
    lines = fx.lines_for_cycle(client, cycle["id"])
    assert len(lines) == 1, f"one lot backs the whole grant, found {len(lines)} lines"

    fx.set_clock(client, "2026-08-04T08:00:00Z")
    test = fx.request_thermal_test(
        client,
        run["id"],
        ctx["sku_id"],
        ctx["program_id"],
        window_start="2026-08-04T08:00:00Z",
        window_end="2026-08-04T12:00:00Z",
        user_id=QUALITY_ENGINEER_USER_ID_ALT,
    )
    get_success_data(
        client.start_lab(test["id"], quality_engineer_headers(QUALITY_ENGINEER_USER_ID_ALT))
    )

    ctx.update(
        {
            "cert_run": cert_run,
            "run": run,
            "run_id": run["id"],
            "lot": lot,
            "lot_id": lot["id"],
            "order": order,
            "order_id": order["id"],
            "cycle": cycle,
            "cycle_id": cycle["id"],
            "line": lines[0],
            "line_id": lines[0]["id"],
            "test": test,
            "test_id": test["id"],
        }
    )
    return ctx


def _condemn(client: InsulationApiClient, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(
        client.record_result(
            ctx["test_id"],
            CONDEMNING_SPECIMENS,
            quality_engineer_headers(QUALITY_ENGINEER_USER_ID_ALT),
        )
    )


def test_the_committed_book_fills_the_contract_order_to_the_bag(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "each served order's `allocated_sqft` becomes its prior allocation plus
    its grant, quantized to two decimal places, its `fill_rate_pct` becomes
    `allocated_sqft` divided by `requested_sqft` multiplied by 100, quantized to two
    decimal places, and its status is **derived** from the comparison: `ALLOCATED` when
    `allocated_sqft` equals `requested_sqft` exactly."

    Design: Difficulty/transitive_cascade/nonconforming_thermal_result_cascades_to_order_backorder_five_hops
    """
    ctx = _committed_book(client)

    assert_field_equals(ctx["line"], "status", "ALLOCATED")
    assert_close(ctx["line"]["allocated_sqft"], 8800.00, 2, "line allocated_sqft")

    order = fx.get_order(client, ctx["order_id"])
    assert_field_equals(order, "status", "ALLOCATED")
    assert_close(order["allocated_sqft"], 8800.00, 2, "order allocated_sqft")
    assert_close(order["fill_rate_pct"], 100.00, 2, "fill_rate_pct")
    assert_field_equals(order, "placed_by_user_id", CHANNEL_BUYER_USER_ID)

    cycle = fx.get_cycle(client, ctx["cycle_id"])
    assert_field_equals(cycle, "peak_season", True)
    assert_close(cycle["total_available_sqft"], 10560.00, 2, "total_available_sqft")
    assert_close(cycle["seasonal_reserve_sqft"], 1584.00, 2, "seasonal_reserve_sqft")
    assert_close(cycle["allocatable_sqft"], 8976.00, 2, "allocatable_sqft")
    assert_close(cycle["allocated_sqft"], 8800.00, 2, "cycle allocated_sqft")
    assert_close(cycle["unallocated_sqft"], 176.00, 2, "unallocated_sqft")

    lot = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(lot, "status", "AVAILABLE")
    assert_close(lot["allocated_sqft"], 8800.00, 2, "lot allocated_sqft")
    assert_close(lot["available_sqft"], 1760.00, 2, "lot available_sqft")


def test_one_condemning_specimen_walks_the_cascade_down_to_a_backorder(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "A `NONCONFORMING` verdict fires the quality cascade in full depth: every
    finished-goods lot of that run whose status is `AVAILABLE` or `ALLOCATED`
    transitions to `QUARANTINED` with `quarantine_reason` `RUN_NONCONFORMING` and
    `available_sqft` forced to 0.00; every allocation line on those lots whose status is
    `PROPOSED` or `ALLOCATED` transitions to `REVOKED` with `revoke_reason`
    `LOT_QUARANTINED`; every affected order's `allocated_sqft`, `fill_rate_pct` and
    `status` are recomputed and re-derived; and every affected cycle's `allocated_sqft`
    and `unallocated_sqft` are recomputed."

    Design: Difficulty/transitive_cascade/nonconforming_thermal_result_cascades_to_order_backorder_five_hops
    """
    ctx = _committed_book(client)

    verdict = _condemn(client, ctx)

    # Hop 0 - the test row itself.
    assert_field_equals(verdict, "conformance_verdict", "NONCONFORMING")
    assert_field_equals(verdict, "status", "COMPLETED")
    assert_field_equals(verdict, "attempt_number", 1)
    assert_close(verdict["min_r_value"], 12.40, 2, "min_r_value")
    assert_close(verdict["mean_r_value"], 12.50, 2, "mean_r_value")
    assert_field_equals(verdict, "recorded_by_user_id", QUALITY_ENGINEER_USER_ID_ALT)

    # Hop 1 - the run's quality dimension only.
    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "qc_status", "NONCONFORMING")
    assert_field_equals(run, "run_status", "PACKAGED")

    # Hop 2 - the finished-goods lot.
    lot = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(lot, "status", "QUARANTINED")
    assert_field_equals(lot, "quarantine_reason", "RUN_NONCONFORMING")
    assert_close(lot["available_sqft"], 0.00, 2, "lot available_sqft")
    assert_close(lot["allocated_sqft"], 0.00, 2, "lot allocated_sqft")

    # Hop 3 - the booked allocation line.
    line = fx.get_line(client, ctx["line_id"])
    assert_field_equals(line, "status", "REVOKED")
    assert_field_equals(line, "revoke_reason", "LOT_QUARANTINED")

    # Hop 4 - the order drops from fully filled straight to backordered.
    order = fx.get_order(client, ctx["order_id"])
    assert_field_equals(order, "status", "BACKORDERED")
    assert_close(order["allocated_sqft"], 0.00, 2, "order allocated_sqft")
    assert_close(order["fill_rate_pct"], 0.00, 2, "fill_rate_pct")

    # Hop 5 - the cycle roll-up.
    cycle = fx.get_cycle(client, ctx["cycle_id"])
    assert_close(cycle["allocated_sqft"], 0.00, 2, "cycle allocated_sqft")
    assert_close(cycle["unallocated_sqft"], 8976.00, 2, "unallocated_sqft")


def test_the_cascade_stops_short_of_the_sku_and_the_cycle_status(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "A `NONCONFORMING` verdict while `attempt_number` is still **strictly
    below** the program's `retest_limit` also moves the test to `COMPLETED`, leaving a
    retest available."

    Design: Difficulty/transitive_cascade/nonconforming_thermal_result_cascades_to_order_backorder_five_hops
    """
    ctx = _committed_book(client)

    _condemn(client, ctx)

    sku = fx.get_product_line(client, ctx["sku_id"])
    assert_field_equals(sku, "nonconformance_count", 0)
    assert_field_equals(sku, "certification_status", "CERTIFIED")

    cycle = fx.get_cycle(client, ctx["cycle_id"])
    assert_field_equals(cycle, "status", "COMMITTED")
    # The reserve arithmetic is not re-run by the cascade, only the two roll-up totals.
    assert_close(cycle["allocatable_sqft"], 8976.00, 2, "allocatable_sqft")

    # The certifying run on the other forming line is untouched by its neighbour.
    cert_run = fx.get_run(client, ctx["cert_run"]["id"])
    assert_field_equals(cert_run, "run_status", "CURING")
    assert_field_equals(cert_run, "qc_status", "CONFORMING")


def _permit_scenario(client: InsulationApiClient) -> Dict[str, Any]:
    """One plant carrying both a phenolic and a formaldehyde-free chain.

    The phenolic SKU is CERTIFIED off a cured run, holds a second run still merely
    SCHEDULED and an OPEN cycle for next month; the free SKU is left waiting in the
    certification queue.
    """
    fx.reset_clock(client)
    program = fx.create_per_specimen_program(client)
    plant = fx.create_plant(client)

    free_binder = fx.create_draft_binder(client, **FREE_BINDER)
    fx.certify_binder(client, free_binder["id"], 0, 3.2, emissions_cert_id="EC-4410")
    phenolic_binder = fx.create_draft_binder(client, **PHENOLIC_BINDER)
    fx.certify_binder(
        client, phenolic_binder["id"], 250, 4.1, emissions_cert_id="EC-4412"
    )

    pl_a = fx.create_product_line(
        client, plant["id"], free_binder["id"], program["id"], **SKU_PL_A
    )
    fx.submit_sku(client, pl_a["id"])
    pl_d = fx.create_product_line(
        client, plant["id"], phenolic_binder["id"], program["id"], **PL_D
    )
    fx.submit_sku(client, pl_d["id"])

    run_d = fx.schedule_run(
        client,
        plant["id"],
        pl_d["id"],
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-03T14:00:00Z",
        line_index=1,
        target_pull_kg=9200.0,
        zone_setpoints_f=list(ZONES_490),
    )
    fx.set_clock(client, "2026-08-03T06:00:00Z")
    fx.start_melt(client, plant["id"], run_d["id"])
    run_d = fx.start_cure(
        client,
        plant["id"],
        run_d["id"],
        avg_zone_temp_f=490.0,
        line_speed_fpm=32.0,
        binder_applied_kg=900.0,
    )
    fx.completed_thermal_test(
        client,
        run_d["id"],
        pl_d["id"],
        program["id"],
        PL_D_SPECIMENS,
        window_start="2026-08-03T16:00:00Z",
        window_end="2026-08-03T20:00:00Z",
    )
    fx.certify_sku(client, pl_d["id"])

    run_d2 = fx.schedule_run(
        client,
        plant["id"],
        pl_d["id"],
        scheduled_start="2026-08-20T06:00:00Z",
        scheduled_end="2026-08-20T14:00:00Z",
        line_index=2,
        target_pull_kg=9200.0,
        zone_setpoints_f=list(ZONES_490),
    )
    cycle_d = fx.open_cycle(
        client,
        plant["id"],
        pl_d["id"],
        period_start="2026-09-01T00:00:00Z",
        period_end="2026-09-30T23:59:59Z",
        allocation_basis="PRO_RATA",
    )
    fx.set_clock(client, "2026-09-01T00:00:00Z")

    return {
        "program": program,
        "plant_id": plant["id"],
        "free_binder_id": free_binder["id"],
        "phenolic_binder_id": phenolic_binder["id"],
        "pl_a_id": pl_a["id"],
        "pl_d_id": pl_d["id"],
        "run_d": run_d,
        "run_d_id": run_d["id"],
        "run_d2_id": run_d2["id"],
        "cycle_d_id": cycle_d["id"],
        "version_before": int(fx.get_plant(client, plant["id"])["version"]),
    }


def _file_period(client: InsulationApiClient, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return fx.file_emissions_report(
        client, ctx["plant_id"], "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z"
    )


def test_the_phenolic_run_books_its_emission_masses_from_the_binder_chemistry(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "`formaldehyde_kg` is `binder_applied_kg` multiplied by the formulation's
    `formaldehyde_ppm` divided by one million, rounded half up to four decimal places -
    parts per million converted to a mass fraction."

    Design: Difficulty/transitive_cascade/permit_exceedance_cascades_through_binder_to_sku_runs_and_cycles
    """
    ctx = _permit_scenario(client)
    run_d = ctx["run_d"]

    assert_close(run_d["dwell_s"], 225.00, 2, "dwell_s")
    assert_close(run_d["cure_index"], 125.00, 2, "cure_index")
    assert_close(run_d["formaldehyde_kg"], 0.2250, 4, "formaldehyde_kg")
    assert_close(run_d["voc_kg"], 3.6900, 4, "voc_kg")


def test_the_period_roll_up_trips_the_formaldehyde_leg_and_freezes_the_melt(
    client: InsulationApiClient,
) -> None:
    """PRD 3.9: "the period exceeded when `reported_formaldehyde_kg` is greater than the
    plant's `formaldehyde_allowance_kg` **or** `reported_voc_kg` is greater than its
    `voc_allowance_kg`."

    Design: Difficulty/transitive_cascade/permit_exceedance_cascades_through_binder_to_sku_runs_and_cycles
    """
    ctx = _permit_scenario(client)

    plant = _file_period(client, ctx)

    assert_close(plant["reported_formaldehyde_kg"], 0.2250, 4, "reported_formaldehyde_kg")
    assert_close(plant["reported_voc_kg"], 3.6900, 4, "reported_voc_kg")
    assert_field_equals(plant, "reported_period_start", "2026-08-01T00:00:00Z")
    assert_field_equals(plant, "reported_period_end", "2026-08-31T23:59:59Z")
    # The formaldehyde leg trips on 0.2250 > 0.200; the VOC leg stays well inside 12.0.
    assert_field_equals(plant, "emissions_status", "EXCEEDANCE")
    assert_field_equals(plant, "melt_posture", "FROZEN")
    assert_field_equals(plant, "posture_reason", "EMISSIONS_EXCEEDANCE")
    assert_field_equals(plant, "version", ctx["version_before"] + 1)


def test_the_freeze_suspends_the_phenolic_chain_and_spares_the_free_chemistry(
    client: InsulationApiClient,
) -> None:
    """PRD 3.9: "Every `CERTIFIED` binder formulation whose `formaldehyde_free` flag is
    false and which is used by a SKU of this plant transitions to `SUSPENDED` -
    formaldehyde-free chemistries are deliberately spared, since they cannot be the
    source of a formaldehyde exceedance."

    Design: Difficulty/transitive_cascade/permit_exceedance_cascades_through_binder_to_sku_runs_and_cycles
    """
    ctx = _permit_scenario(client)

    _file_period(client, ctx)

    phenolic = get_success_data(
        client.get_binder_formulation(
            ctx["phenolic_binder_id"], quality_engineer_headers()
        )
    )
    free = get_success_data(
        client.get_binder_formulation(ctx["free_binder_id"], quality_engineer_headers())
    )
    assert_field_equals(phenolic, "status", "SUSPENDED")
    assert_field_equals(free, "status", "CERTIFIED")

    assert_field_equals(
        fx.get_product_line(client, ctx["pl_d_id"]), "certification_status", "SUSPENDED"
    )
    assert_field_equals(
        fx.get_product_line(client, ctx["pl_a_id"]),
        "certification_status",
        "PENDING_CERTIFICATION",
    )


def test_the_freeze_holds_the_scheduled_run_and_cancels_the_open_cycle(
    client: InsulationApiClient,
) -> None:
    """PRD 3.9: "Every production run of the plant whose `run_status` is `SCHEDULED`
    transitions `SCHEDULED -> HELD` with `hold_reason` `PLANT_FROZEN`."

    Design: Difficulty/transitive_cascade/permit_exceedance_cascades_through_binder_to_sku_runs_and_cycles
    """
    ctx = _permit_scenario(client)

    _file_period(client, ctx)

    held = fx.get_run(client, ctx["run_d2_id"])
    assert_field_equals(held, "run_status", "HELD")
    assert_field_equals(held, "hold_reason", "PLANT_FROZEN")

    # The cured run is past the hold gate and keeps both of its dimensions.
    cured = fx.get_run(client, ctx["run_d_id"])
    assert_field_equals(cured, "run_status", "CURING")
    assert_field_equals(cured, "qc_status", "CONFORMING")

    cycle = fx.get_cycle(client, ctx["cycle_d_id"])
    assert_field_equals(cycle, "status", "CANCELLED")
