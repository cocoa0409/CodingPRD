"""Dual-variant calculations: one changeover priced twice, one specimen array judged twice.

Queue A / dual_variant_calc.
"""

from typing import Any, Dict

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import InsulationApiClient
from test_helpers.assertions import (
    assert_close,
    assert_field_equals,
    assert_mass,
    assert_ratio,
)
from test_helpers.test_users import (
    QUALITY_ENGINEER_USER_ID_ALT,
    plant_operator_headers,
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

PL_A = {
    "sku": "R13-15-UF",
    "density_pcf": 0.80,
    "facing_type": "UNFACED",
    "width_in": 15.0,
    "thickness_in": 3.5,
    "declared_r_value": 13.0,
    "bag_sqft": 88.0,
    "bale_volume_ft3": 21.0,
    "bale_mass_kg": 12.5,
    "compression_ratio": 6.0,
    "mass_rate_kg_per_min": 34.5,
}

PL_B = {
    "sku": "R19-23-KR",
    "density_pcf": 1.20,
    "facing_type": "KRAFT",
    "width_in": 23.0,
    "thickness_in": 6.25,
    "declared_r_value": 19.0,
    "bag_sqft": 49.0,
    "bale_volume_ft3": 25.5,
    "bale_mass_kg": 15.0,
    "compression_ratio": 5.0,
    "mass_rate_kg_per_min": 41.0,
}

ZONES_470 = [470.0, 470.0, 470.0, 470.0]
ZONES_480 = [480.0, 480.0, 480.0, 480.0]


def _changeover_scenario(client: InsulationApiClient) -> Dict[str, Any]:
    """Plant NWK, two SKUs on one line, outgoing run PACKAGED and incoming SCHEDULED."""
    fx.reset_clock(client)
    program = fx.create_per_specimen_program(client)
    plant = fx.create_plant(client)
    binder = fx.create_certified_binder(client, **FREE_BINDER)
    pl_a = fx.create_product_line(client, plant["id"], binder["id"], program["id"], **PL_A)
    pl_b = fx.create_product_line(client, plant["id"], binder["id"], program["id"], **PL_B)

    run_a = fx.schedule_run(
        client,
        plant["id"],
        pl_a["id"],
        line_index=1,
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-03T14:00:00Z",
        target_pull_kg=9200.0,
        zone_setpoints_f=ZONES_470,
    )
    run_b = fx.schedule_run(
        client,
        plant["id"],
        pl_b["id"],
        line_index=1,
        scheduled_start="2026-08-03T15:00:00Z",
        scheduled_end="2026-08-03T23:00:00Z",
        target_pull_kg=9200.0,
        zone_setpoints_f=ZONES_480,
    )

    fx.set_clock(client, "2026-08-03T06:00:00Z")
    fx.start_melt(client, plant["id"], run_a["id"], [])
    fx.start_cure(
        client,
        plant["id"],
        run_a["id"],
        avg_zone_temp_f=470.0,
        line_speed_fpm=40.0,
        binder_applied_kg=900.0,
    )
    fx.package_run(client, plant["id"], run_a["id"], 120)
    fx.set_clock(client, "2026-08-03T16:00:00Z")

    return {
        "plant": plant,
        "plant_id": plant["id"],
        "pl_a": pl_a,
        "pl_b": pl_b,
        "run_a": run_a,
        "run_b": run_b,
        "operator": plant_operator_headers(plant["id"]),
    }


def _open_changeover(client: InsulationApiClient, ctx: Dict[str, Any]) -> Dict[str, Any]:
    from prd_bench_local_runner.testing import get_success_data

    payload = f.changeover_payload(
        ctx["plant_id"],
        ctx["run_a"]["id"],
        ctx["run_b"]["id"],
        1,
        "2026-08-03T14:00:00Z",
        "2026-08-03T15:00:00Z",
    )
    return get_success_data(client.create_changeover(payload, ctx["operator"]), 201)


def test_provisional_purge_estimate_prices_density_width_and_facing_steps(
    client: InsulationApiClient,
) -> None:
    """Opening the changeover books the time-based estimate on the outgoing run.

    PRD 3.5: "`purge_minutes` is then the sum of four terms: a base transition
    allowance of 12 minutes; a density term equal to `density_delta_pct`
    multiplied by 0.40 minutes per percentage point, rounded half up to two
    decimal places and then **capped at 20 minutes**; a further 8 minutes if and
    only if `from_width_in` and `to_width_in` differ; and a further 15 minutes if
    and only if `facing_changed` is true."

    Design: Difficulty/dual_variant_calc/changeover_scrap_provisional_versus_reconciled_on_same_event
    """
    ctx = _changeover_scenario(client)
    changeover = _open_changeover(client, ctx)

    assert_ratio(changeover["density_delta_pct"], 50.0, "density_delta_pct")
    assert_close(changeover["purge_minutes"], 55.00, 2, "purge_minutes")
    assert_mass(changeover["provisional_scrap_kg"], 1897.50, "provisional_scrap_kg")
    assert_field_equals(changeover, "facing_changed", True)
    assert_close(changeover["from_width_in"], 15.0, 2, "from_width_in")
    assert_close(changeover["to_width_in"], 23.0, 2, "to_width_in")
    assert_field_equals(changeover, "status", "OPEN")

    outgoing = fx.get_run(client, ctx["run_a"]["id"])
    assert_mass(outgoing["changeover_scrap_kg"], 1897.50, "changeover_scrap_kg")


def test_reconciled_scrap_overwrites_the_provisional_figure_and_may_run_negative(
    client: InsulationApiClient,
) -> None:
    """Closing against the scale replaces the estimate and records the variance.

    PRD 3.5: "`scrap_variance_kg` - how far the time-based estimate missed the
    scale - is `weighed_trim_kg` less `provisional_scrap_kg`, rounded half up to
    two decimal places, and it may legitimately be negative when the estimate ran
    high."

    Design: Difficulty/dual_variant_calc/changeover_scrap_provisional_versus_reconciled_on_same_event
    """
    from prd_bench_local_runner.testing import get_success_data

    ctx = _changeover_scenario(client)
    changeover = _open_changeover(client, ctx)
    provisional = changeover["provisional_scrap_kg"]

    closed = get_success_data(
        client.close_changeover(
            changeover["id"],
            f.close_changeover_payload(1620.0, 1377.0),
            ctx["operator"],
        )
    )

    assert_mass(closed["reconciled_scrap_kg"], 243.00, "reconciled_scrap_kg")
    assert_mass(closed["scrap_variance_kg"], -277.50, "scrap_variance_kg")
    assert closed["reconciled_scrap_kg"] != provisional, (
        "the reconciled figure must differ from the provisional one on this row"
    )
    assert_field_equals(closed, "status", "CLOSED")

    outgoing = fx.get_run(client, ctx["run_a"]["id"])
    assert_mass(
        outgoing["changeover_scrap_kg"], 243.00, "changeover_scrap_kg after close"
    )


def test_recovered_trim_is_staged_back_into_the_yard_as_changeover_scrap(
    client: InsulationApiClient,
) -> None:
    """The recovered portion of the weighed trim returns to the cullet pile.

    PRD 3.5: "When `recovered_cullet_kg` is greater than zero, closing the
    changeover cascade-creates one cullet batch in status `STAGED` with
    `source_type` `CHANGEOVER_SCRAP`, `source_run_id` set to the outgoing run, and
    `mass_kg` equal to the recovered mass."

    Design: Difficulty/dual_variant_calc/changeover_scrap_provisional_versus_reconciled_on_same_event
    """
    from prd_bench_local_runner.testing import get_success_data

    ctx = _changeover_scenario(client)
    changeover = _open_changeover(client, ctx)
    get_success_data(
        client.close_changeover(
            changeover["id"],
            f.close_changeover_payload(1620.0, 1377.0),
            ctx["operator"],
        )
    )

    batches = fx.cullet_batches_for_plant(
        client, ctx["plant_id"], source_run_id=ctx["run_a"]["id"]
    )
    assert len(batches) == 1, f"expected exactly one recovered batch, got {len(batches)}"
    batch = batches[0]
    assert_field_equals(batch, "source_type", "CHANGEOVER_SCRAP")
    assert_field_equals(batch, "status", "STAGED")
    assert_field_equals(batch, "source_run_id", ctx["run_a"]["id"])
    assert_mass(batch["mass_kg"], 1377.00, "mass_kg")

    plant = fx.get_plant(client, ctx["plant_id"])
    assert_mass(plant["cullet_received_kg_ytd"], 1377.00, "cullet_received_kg_ytd")
    assert_mass(plant["cullet_on_hand_kg"], 1377.00, "cullet_on_hand_kg")


PL_C = dict(PL_A, sku="R13-16-UF-LM", width_in=16.0)

IDENTICAL_SPECIMENS = [12.70, 13.10, 12.40]


def _two_basis_scenario(client: InsulationApiClient) -> Dict[str, Any]:
    """One plant, two programs differing only in conformance_basis, one IN_LAB test each."""
    fx.reset_clock(client)
    prog_ps = fx.create_per_specimen_program(client)
    prog_lm = fx.create_lot_mean_program(client)
    plant = fx.create_plant(client)
    binder = fx.create_certified_binder(client, **FREE_BINDER)
    pl_a = fx.create_product_line(client, plant["id"], binder["id"], prog_ps["id"], **PL_A)
    pl_c = fx.create_product_line(client, plant["id"], binder["id"], prog_lm["id"], **PL_C)

    run_a = fx.schedule_run(
        client,
        plant["id"],
        pl_a["id"],
        line_index=1,
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-03T14:00:00Z",
        target_pull_kg=9200.0,
        zone_setpoints_f=ZONES_470,
    )
    run_c = fx.schedule_run(
        client,
        plant["id"],
        pl_c["id"],
        line_index=2,
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-03T14:00:00Z",
        target_pull_kg=9200.0,
        zone_setpoints_f=ZONES_470,
    )
    fx.set_clock(client, "2026-08-03T06:00:00Z")
    for run in (run_a, run_c):
        fx.start_melt(client, plant["id"], run["id"], [])
        fx.start_cure(
            client,
            plant["id"],
            run["id"],
            avg_zone_temp_f=470.0,
            line_speed_fpm=40.0,
            binder_applied_kg=900.0,
        )

    test_ps = fx.request_thermal_test(
        client,
        run_a["id"],
        pl_a["id"],
        prog_ps["id"],
        "2026-08-04T08:00:00Z",
        "2026-08-04T12:00:00Z",
        user_id=QUALITY_ENGINEER_USER_ID_ALT,
    )
    test_lm = fx.request_thermal_test(
        client,
        run_c["id"],
        pl_c["id"],
        prog_lm["id"],
        "2026-08-04T08:00:00Z",
        "2026-08-04T12:00:00Z",
        user_id=QUALITY_ENGINEER_USER_ID_ALT,
    )
    return {
        "prog_ps": prog_ps,
        "prog_lm": prog_lm,
        "plant_id": plant["id"],
        "pl_a": pl_a,
        "pl_c": pl_c,
        "run_a": run_a,
        "run_c": run_c,
        "test_ps": test_ps,
        "test_lm": test_lm,
    }


def test_per_specimen_basis_condemns_the_lot_on_its_weakest_specimen(
    client: InsulationApiClient,
) -> None:
    """The PER_SPECIMEN program judges the minimum specimen against the floor.

    PRD 3.6: "On a `PER_SPECIMEN` basis the verdict is `CONFORMING` when
    `min_r_value` is greater than or equal to the floor and `NONCONFORMING`
    otherwise - every single specimen must clear the floor."

    Design: Difficulty/dual_variant_calc/thermal_verdict_per_specimen_versus_lot_mean_on_identical_specimens
    """
    ctx = _two_basis_scenario(client)
    recorded = fx.record_thermal_result(
        client,
        ctx["test_ps"]["id"],
        IDENTICAL_SPECIMENS,
        user_id=QUALITY_ENGINEER_USER_ID_ALT,
    )

    assert_field_equals(recorded, "conformance_basis", "PER_SPECIMEN")
    assert_close(recorded["declared_r_value_at_test"], 13.0, 2, "declared_r_value_at_test")
    assert_field_equals(recorded, "specimen_count", 3)
    assert_close(recorded["mean_r_value"], 12.73, 2, "mean_r_value")
    assert_close(recorded["min_r_value"], 12.40, 2, "min_r_value")
    assert_field_equals(recorded, "conformance_verdict", "NONCONFORMING")
    assert_field_equals(recorded, "status", "COMPLETED")


def test_lot_mean_basis_clears_the_same_specimens_carried_by_the_mean(
    client: InsulationApiClient,
) -> None:
    """The LOT_MEAN program judges the mean, so a weak specimen is carried.

    PRD 3.6: "On a `LOT_MEAN` basis the verdict is `CONFORMING` when
    `mean_r_value` is greater than or equal to the floor and `NONCONFORMING`
    otherwise - a weak specimen may be carried by strong ones."

    Design: Difficulty/dual_variant_calc/thermal_verdict_per_specimen_versus_lot_mean_on_identical_specimens
    """
    ctx = _two_basis_scenario(client)
    recorded = fx.record_thermal_result(
        client,
        ctx["test_lm"]["id"],
        IDENTICAL_SPECIMENS,
        user_id=QUALITY_ENGINEER_USER_ID_ALT,
    )

    assert_field_equals(recorded, "conformance_basis", "LOT_MEAN")
    assert_close(recorded["declared_r_value_at_test"], 13.0, 2, "declared_r_value_at_test")
    assert_field_equals(recorded, "specimen_count", 3)
    assert_close(recorded["mean_r_value"], 12.73, 2, "mean_r_value")
    assert_close(recorded["min_r_value"], 12.40, 2, "min_r_value")
    assert_field_equals(recorded, "conformance_verdict", "CONFORMING")
    assert_field_equals(recorded, "status", "COMPLETED")


def test_identical_specimens_drive_opposite_run_quality_dimensions(
    client: InsulationApiClient,
) -> None:
    """Byte-identical specimen arrays diverge because only the pinned basis differs.

    PRD 3.6: "On the run, the quality dimension advances `SAMPLED -> CONFORMING` or
    `SAMPLED -> NONCONFORMING` (and `RETEST_PENDING -> CONFORMING` or
    `RETEST_PENDING -> NONCONFORMING` on a retest attempt) to match the verdict."

    Design: Difficulty/dual_variant_calc/thermal_verdict_per_specimen_versus_lot_mean_on_identical_specimens
    """
    ctx = _two_basis_scenario(client)
    ps = fx.record_thermal_result(
        client,
        ctx["test_ps"]["id"],
        IDENTICAL_SPECIMENS,
        user_id=QUALITY_ENGINEER_USER_ID_ALT,
    )
    lm = fx.record_thermal_result(
        client,
        ctx["test_lm"]["id"],
        IDENTICAL_SPECIMENS,
        user_id=QUALITY_ENGINEER_USER_ID_ALT,
    )

    assert ps["conformance_verdict"] != lm["conformance_verdict"], (
        "the two pinned bases must disagree on byte-identical specimen_r_values"
    )
    assert_field_equals(
        fx.get_run(client, ctx["run_a"]["id"]), "qc_status", "NONCONFORMING"
    )
    assert_field_equals(fx.get_run(client, ctx["run_c"]["id"]), "qc_status", "CONFORMING")
