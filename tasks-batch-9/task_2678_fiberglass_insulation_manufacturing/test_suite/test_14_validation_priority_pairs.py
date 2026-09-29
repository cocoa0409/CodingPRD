"""Priority-ordered validation pairs: one request that breaks two rules at once must
answer with the earlier rung of the global ladder.

Queue A / priority_pair_validation_conflict.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import InsulationApiClient
from test_helpers.api_errors import ApiErrors
from test_helpers.assertions import assert_close, assert_field_equals
from test_helpers.constants import SKU_PL_A, SKU_PL_B, SKU_PL_C, ZONES_470, ZONES_480
from test_helpers.test_users import corporate_ops_headers, plant_operator_headers

FREE_BINDER = {
    "code": "BF-FREE-1",
    "formaldehyde_free": True,
    "formaldehyde_ppm": 0,
    "voc_g_per_kg": 3.2,
    "min_cure_temp_f": 420.0,
    "min_dwell_s": 150.0,
    "loi_target_pct": 4.5,
}

DRAFT_BINDER = {
    "code": "BF-DRAFT-1",
    "formaldehyde_free": True,
    "formaldehyde_ppm": 0,
    "voc_g_per_kg": 3.0,
    "min_cure_temp_f": 420.0,
    "min_dwell_s": 150.0,
    "loi_target_pct": 4.4,
}

PL_E = {
    "sku": "R30-24-FSK",
    "form": "BATT",
    "density_pcf": 2.00,
    "facing_type": "FSK",
    "width_in": 24.0,
    "thickness_in": 10.0,
    "declared_r_value": 30.0,
    "bag_sqft": 32.0,
    "bale_volume_ft3": 30.0,
    "bale_mass_kg": 18.0,
    "compression_ratio": 6.0,
    "mass_rate_kg_per_min": 45.0,
}

SHORT_ZONES = [470.0, 470.0, 470.0]


def _two_binder_scenario(client: InsulationApiClient) -> Dict[str, Any]:
    """One SKU on a CERTIFIED chemistry, one on a chemistry still in DRAFT."""
    fx.reset_clock(client)
    program = fx.create_per_specimen_program(client)
    plant = fx.create_plant(client)
    certified = fx.create_draft_binder(client, **FREE_BINDER)
    fx.certify_binder(client, certified["id"], 0, 3.2, emissions_cert_id="EC-4411")
    drafted = fx.create_draft_binder(client, **DRAFT_BINDER)

    pl_a = fx.create_product_line(
        client, plant["id"], certified["id"], program["id"], **SKU_PL_A
    )
    pl_f = fx.create_product_line(
        client,
        plant["id"],
        drafted["id"],
        program["id"],
        **dict(SKU_PL_A, sku="R13-15-UF-DR"),
    )
    return {
        "plant_id": plant["id"],
        "program_id": program["id"],
        "certified_binder_id": certified["id"],
        "draft_binder_id": drafted["id"],
        "pl_a": pl_a["id"],
        "pl_f": pl_f["id"],
        "operator": plant_operator_headers(plant["id"]),
    }


def _schedule(
    client: InsulationApiClient,
    ctx: Dict[str, Any],
    product_line_id: str,
    zones: Any,
):
    payload = f.production_run_payload(
        ctx["plant_id"],
        product_line_id,
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-03T14:00:00Z",
        line_index=1,
        target_pull_kg=9200.0,
        zone_setpoints_f=list(zones),
    )
    return client.create_production_run(payload, ctx["operator"])


def test_the_uncertified_binder_is_reported_ahead_of_the_short_zone_array(
    client: InsulationApiClient,
) -> None:
    """PRD 2.8: "Every write endpoint evaluates the rules applicable to it in one strict
    global order and returns the **first** violation it encounters."

    Design: Difficulty/priority_pair_validation_conflict/uncertified_binder_outranks_oven_zone_mismatch_on_run_scheduling
    """
    ctx = _two_binder_scenario(client)

    # Two rules broken at once: rung 10's certified-binder gate and rung 12's zone array.
    resp = _schedule(client, ctx, ctx["pl_f"], SHORT_ZONES)

    validate_error(resp, ApiErrors.BINDER_NOT_CERTIFIED)

    _data, meta = validate_paginated(
        client.list_production_runs(
            corporate_ops_headers(), {"plant_id": ctx["plant_id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 0, "a rejected schedule must not leave a run behind"


def test_fixing_only_the_binder_surfaces_the_zone_mismatch_underneath(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "Last, the array length of `zone_setpoints_f` must equal the plant's
    `oven_zone_count` exactly and every setpoint in it must be positive, or the request
    is refused with `ERR_OVEN_ZONE_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/uncertified_binder_outranks_oven_zone_mismatch_on_run_scheduling
    """
    ctx = _two_binder_scenario(client)

    resp = _schedule(client, ctx, ctx["pl_a"], SHORT_ZONES)

    validate_error(resp, ApiErrors.OVEN_ZONE_MISMATCH)


def test_fixing_only_the_zone_array_still_reports_the_uncertified_binder(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "The SKU's binder formulation must be `CERTIFIED`, or the request is
    refused with `ERR_BINDER_NOT_CERTIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/uncertified_binder_outranks_oven_zone_mismatch_on_run_scheduling
    """
    ctx = _two_binder_scenario(client)

    resp = _schedule(client, ctx, ctx["pl_f"], ZONES_470)

    validate_error(resp, ApiErrors.BINDER_NOT_CERTIFIED)


def test_fixing_both_faults_schedules_the_run(client: InsulationApiClient) -> None:
    """PRD 3.4: "The new run lands with `run_status` `SCHEDULED`, `qc_status`
    `UNSAMPLED`, `hold_reason` null, `changeover_scrap_kg` 0.00, `cullet_charged_kg`
    0.00, and every other mass, cure and emissions figure null."

    Design: Difficulty/priority_pair_validation_conflict/uncertified_binder_outranks_oven_zone_mismatch_on_run_scheduling
    """
    ctx = _two_binder_scenario(client)

    run = get_success_data(_schedule(client, ctx, ctx["pl_a"], ZONES_470), 201)

    assert_field_equals(run, "run_status", "SCHEDULED")
    assert_field_equals(run, "qc_status", "UNSAMPLED")
    assert run["hold_reason"] is None
    assert_close(run["changeover_scrap_kg"], 0.00, 2, "changeover_scrap_kg")
    assert_close(run["cullet_charged_kg"], 0.00, 2, "cullet_charged_kg")


def _changeover_scenario(client: InsulationApiClient) -> Dict[str, Any]:
    """Line 1 carries four back-to-back runs; the first two are driven to PACKAGED and
    a first changeover already occupies the window around 14:00-15:00."""
    fx.reset_clock(client)
    program = fx.create_per_specimen_program(client)
    plant = fx.create_plant(client)
    binder = fx.create_draft_binder(client, **FREE_BINDER)
    fx.certify_binder(client, binder["id"], 0, 3.2, emissions_cert_id="EC-4411")

    def sku(overrides: Dict[str, Any]) -> str:
        return fx.create_product_line(
            client, plant["id"], binder["id"], program["id"], **overrides
        )["id"]

    pl_a = sku(dict(SKU_PL_A))
    pl_b = sku(dict(SKU_PL_B))
    pl_c = sku(dict(SKU_PL_C))
    pl_e = sku(dict(PL_E))

    def run(product_line_id: str, start: str, end: str, pull: float) -> Dict[str, Any]:
        return fx.schedule_run(
            client,
            plant["id"],
            product_line_id,
            scheduled_start=start,
            scheduled_end=end,
            line_index=1,
            target_pull_kg=pull,
            zone_setpoints_f=list(ZONES_480),
        )

    run_1 = run(pl_b, "2026-08-03T06:00:00Z", "2026-08-03T14:00:00Z", 9200.0)
    run_2 = run(pl_a, "2026-08-03T15:00:00Z", "2026-08-03T20:00:00Z", 1500.0)
    run_3 = run(pl_e, "2026-08-03T21:00:00Z", "2026-08-04T05:00:00Z", 1500.0)
    run_4 = run(pl_c, "2026-08-04T06:00:00Z", "2026-08-04T14:00:00Z", 1500.0)

    def drive(run_id: str, bags: int) -> None:
        fx.start_melt(client, plant["id"], run_id)
        fx.start_cure(
            client,
            plant["id"],
            run_id,
            avg_zone_temp_f=480.0,
            line_speed_fpm=36.0,
            binder_applied_kg=900.0,
        )
        fx.package_run(client, plant["id"], run_id, bags_produced=bags)

    operator = plant_operator_headers(plant["id"])

    fx.set_clock(client, "2026-08-03T06:00:00Z")
    drive(run_1["id"], 120)

    # The incumbent purge window; inflated by 30 minutes a side it covers
    # [13:30, 15:30] on line 1. Its width step is 8 inches exactly - the plant's ceiling.
    first = get_success_data(
        client.create_changeover(
            f.changeover_payload(
                plant["id"],
                run_1["id"],
                run_2["id"],
                1,
                "2026-08-03T14:00:00Z",
                "2026-08-03T15:00:00Z",
            ),
            operator,
        ),
        201,
    )

    fx.set_clock(client, "2026-08-03T15:00:00Z")
    drive(run_2["id"], 20)

    return {
        "plant_id": plant["id"],
        "operator": operator,
        "first_changeover": first,
        "run_1": run_1["id"],
        "run_2": run_2["id"],
        "run_3": run_3["id"],
        "run_4": run_4["id"],
    }


def _open_changeover(
    client: InsulationApiClient,
    ctx: Dict[str, Any],
    incoming_run_id: str,
    window_start: str,
    window_end: str,
):
    return client.create_changeover(
        f.changeover_payload(
            ctx["plant_id"],
            ctx["run_2"],
            incoming_run_id,
            1,
            window_start,
            window_end,
        ),
        ctx["operator"],
    )


def test_the_crowded_purge_window_is_reported_ahead_of_the_oversized_width_step(
    client: InsulationApiClient,
) -> None:
    """PRD 2.8: "Every write endpoint evaluates the rules applicable to it in one strict
    global order and returns the **first** violation it encounters."

    Design: Difficulty/priority_pair_validation_conflict/changeover_window_conflict_outranks_width_change_out_of_range
    """
    ctx = _changeover_scenario(client)
    assert_field_equals(ctx["first_changeover"], "status", "OPEN")
    assert_close(ctx["first_changeover"]["from_width_in"], 23.0, 2, "from_width_in")
    assert_close(ctx["first_changeover"]["to_width_in"], 15.0, 2, "to_width_in")

    # Inflated to [15:15, 16:45] this window intersects the incumbent's [13:30, 15:30],
    # and the width step to the 24-inch SKU is 9 inches against a ceiling of 8.
    resp = _open_changeover(
        client, ctx, ctx["run_3"], "2026-08-03T15:45:00Z", "2026-08-03T16:15:00Z"
    )

    validate_error(resp, ApiErrors.CHANGEOVER_WINDOW_CONFLICT)

    _data, meta = validate_paginated(
        client.list_changeovers(
            corporate_ops_headers(), {"plant_id": ctx["plant_id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 1, "the rejected changeover must not have been opened"


def test_moving_the_window_clear_surfaces_the_width_step_underneath(
    client: InsulationApiClient,
) -> None:
    """PRD 3.5: "the absolute difference between the incoming SKU's `width_in` and the
    outgoing SKU's `width_in` must be no greater than the plant's `max_width_change_in`,
    or the request is refused with `ERR_WIDTH_CHANGE_OUT_OF_RANGE`."

    Design: Difficulty/priority_pair_validation_conflict/changeover_window_conflict_outranks_width_change_out_of_range
    """
    ctx = _changeover_scenario(client)

    # Inflated to [16:00, 17:30] - clear of the incumbent's [13:30, 15:30].
    resp = _open_changeover(
        client, ctx, ctx["run_3"], "2026-08-03T16:30:00Z", "2026-08-03T17:00:00Z"
    )

    validate_error(resp, ApiErrors.WIDTH_CHANGE_OUT_OF_RANGE)


def test_a_legal_width_step_in_the_crowded_window_still_reports_the_conflict(
    client: InsulationApiClient,
) -> None:
    """PRD 3.5: "the inflated interval of a new changeover must not intersect the
    identically inflated interval of any other changeover on the same plant and
    `line_index` whose status is `OPEN` or `CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/changeover_window_conflict_outranks_width_change_out_of_range
    """
    ctx = _changeover_scenario(client)

    # The 16-inch SKU is a 1-inch step off the outgoing 15-inch SKU, so only the
    # window rule is broken.
    resp = _open_changeover(
        client, ctx, ctx["run_4"], "2026-08-03T15:45:00Z", "2026-08-03T16:15:00Z"
    )

    validate_error(resp, ApiErrors.CHANGEOVER_WINDOW_CONFLICT)


def test_clearing_both_faults_opens_the_second_changeover(
    client: InsulationApiClient,
) -> None:
    """PRD 3.5: "`from_density_pcf` and `to_density_pcf` take the outgoing and incoming
    SKUs' `density_pcf`, `from_width_in` and `to_width_in` take their `width_in`, and
    `facing_changed` is true exactly when the two SKUs differ in `facing_type`."

    Design: Difficulty/priority_pair_validation_conflict/changeover_window_conflict_outranks_width_change_out_of_range
    """
    ctx = _changeover_scenario(client)

    second = get_success_data(
        _open_changeover(
            client, ctx, ctx["run_4"], "2026-08-03T16:30:00Z", "2026-08-03T17:00:00Z"
        ),
        201,
    )

    assert_field_equals(second, "status", "OPEN")
    assert_close(second["from_width_in"], 15.0, 2, "from_width_in")
    assert_close(second["to_width_in"], 16.0, 2, "to_width_in")
    assert_field_equals(second, "facing_changed", False)
