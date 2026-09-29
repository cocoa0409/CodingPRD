"""Temporal occupancy of two different resources: a forming line held pairwise over
half-open intervals, and a laboratory held by an aggregate count over closed windows.

Queue A / resource_temporal_overlap.
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
from test_helpers.constants import SKU_PL_A, ZONES_470
from test_helpers.test_users import (
    QUALITY_ENGINEER_USER_ID_ALT,
    corporate_ops_headers,
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


def _line_one_occupied(client: InsulationApiClient) -> Dict[str, Any]:
    """RUN-1 holds line 1 over [06:00, 14:00) on 2026-08-03 in status SCHEDULED."""
    ctx = fx.base_setup(
        client, binder_overrides=dict(FREE_BINDER), sku_overrides=dict(SKU_PL_A)
    )
    run_1 = fx.schedule_run(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-03T14:00:00Z",
        line_index=1,
        target_pull_kg=9200.0,
        zone_setpoints_f=list(ZONES_470),
    )
    assert_field_equals(run_1, "run_status", "SCHEDULED")
    ctx["run_1"] = run_1
    ctx["run_1_id"] = run_1["id"]
    return ctx


def _schedule_attempt(
    client: InsulationApiClient,
    ctx: Dict[str, Any],
    start: str,
    end: str,
    line_index: int = 1,
):
    payload = f.production_run_payload(
        ctx["plant_id"],
        ctx["sku_id"],
        scheduled_start=start,
        scheduled_end=end,
        line_index=line_index,
        target_pull_kg=9200.0,
        zone_setpoints_f=list(ZONES_470),
    )
    return client.create_production_run(payload, ctx["operator"])


def _runs_on_line(client: InsulationApiClient, plant_id: str, line_index: int) -> int:
    _data, meta = validate_paginated(
        client.list_production_runs(
            corporate_ops_headers(),
            {"plant_id": plant_id, "line_index": line_index, "limit": 100},
        )
    )
    return int(meta["total_count"])


def test_a_one_second_overlap_on_the_same_line_is_refused(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "the half-open interval running from `scheduled_start` up to but not
    including `scheduled_end` must not overlap the interval of any other run on the same
    plant and the same `line_index` whose `run_status` is `SCHEDULED`, `HELD`, `MELTING`
    or `CURING`, and a violation returns `ERR_LINE_OCCUPANCY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/forming_line_occupancy_is_half_open_and_scoped_per_line
    """
    ctx = _line_one_occupied(client)

    resp = _schedule_attempt(
        client, ctx, "2026-08-03T13:59:59Z", "2026-08-03T21:00:00Z"
    )

    validate_error(resp, ApiErrors.LINE_OCCUPANCY_CONFLICT)
    assert _runs_on_line(client, ctx["plant_id"], 1) == 1


def test_a_run_starting_exactly_where_the_incumbent_ends_is_accepted(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "Because the interval is half-open, two back-to-back runs that share an
    endpoint - one ending exactly where the next begins - do **not** conflict, and the
    comparison is made pairwise against each live run rather than against an aggregate."

    Design: Difficulty/resource_temporal_overlap/forming_line_occupancy_is_half_open_and_scoped_per_line
    """
    ctx = _line_one_occupied(client)

    run = get_success_data(
        _schedule_attempt(client, ctx, "2026-08-03T14:00:00Z", "2026-08-03T22:00:00Z"),
        201,
    )

    assert_field_equals(run, "run_status", "SCHEDULED")
    assert_field_equals(run, "qc_status", "UNSAMPLED")
    assert run["hold_reason"] is None
    assert_field_equals(run, "version", 1)
    assert _runs_on_line(client, ctx["plant_id"], 1) == 2


def test_a_run_ending_exactly_where_the_incumbent_begins_is_accepted(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "two back-to-back runs that share an endpoint - one ending exactly where
    the next begins - do **not** conflict."

    Design: Difficulty/resource_temporal_overlap/forming_line_occupancy_is_half_open_and_scoped_per_line
    """
    ctx = _line_one_occupied(client)

    run = get_success_data(
        _schedule_attempt(client, ctx, "2026-08-03T05:00:00Z", "2026-08-03T06:00:00Z"),
        201,
    )

    assert_field_equals(run, "run_status", "SCHEDULED")
    assert_field_equals(run, "version", 1)


def test_the_same_window_on_the_neighbouring_line_is_free(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "Scheduling a run is a `PlantOperator` action and it reserves one forming
    line for one window."

    Design: Difficulty/resource_temporal_overlap/forming_line_occupancy_is_half_open_and_scoped_per_line
    """
    ctx = _line_one_occupied(client)

    run = get_success_data(
        _schedule_attempt(
            client, ctx, "2026-08-03T13:59:59Z", "2026-08-03T21:00:00Z", line_index=2
        ),
        201,
    )

    assert_field_equals(run, "run_status", "SCHEDULED")
    assert_field_equals(run, "line_index", 2)
    assert _runs_on_line(client, ctx["plant_id"], 1) == 1
    assert _runs_on_line(client, ctx["plant_id"], 2) == 1


def test_an_aborted_run_releases_the_line_it_was_holding(
    client: InsulationApiClient,
) -> None:
    """PRD 3.4: "Aborting is the compensating exit and is available from `SCHEDULED`,
    `MELTING` or `CURING`, each landing on the terminal `ABORTED`."

    Design: Difficulty/resource_temporal_overlap/forming_line_occupancy_is_half_open_and_scoped_per_line
    """
    ctx = _line_one_occupied(client)
    later = get_success_data(
        _schedule_attempt(client, ctx, "2026-08-03T14:00:00Z", "2026-08-03T22:00:00Z"),
        201,
    )

    aborted = get_success_data(
        client.abort_run(later["id"], "line rebuilt", ctx["operator"])
    )
    assert_field_equals(aborted, "run_status", "ABORTED")

    # [16:00, 20:00) sits wholly inside the aborted run's window and is accepted anyway.
    replacement = get_success_data(
        _schedule_attempt(client, ctx, "2026-08-03T16:00:00Z", "2026-08-03T20:00:00Z"),
        201,
    )

    assert_field_equals(replacement, "run_status", "SCHEDULED")
    assert_field_equals(replacement, "version", 1)


CONFORMING_SPECIMENS = [13.10, 13.20, 12.90]


def _three_curing_runs(client: InsulationApiClient) -> Dict[str, Any]:
    """Two lab windows already IN_LAB on a program that allows two, plus a third test
    still REQUESTED whose closed window touches one and overlaps the other."""
    ctx = fx.base_setup(
        client, binder_overrides=dict(FREE_BINDER), sku_overrides=dict(SKU_PL_A)
    )

    def schedule(line_index: int, start: str, end: str) -> str:
        return fx.schedule_run(
            client,
            ctx["plant_id"],
            ctx["sku_id"],
            scheduled_start=start,
            scheduled_end=end,
            line_index=line_index,
            target_pull_kg=9200.0,
            zone_setpoints_f=list(ZONES_470),
        )["id"]

    run_1 = schedule(1, "2026-08-03T06:00:00Z", "2026-08-03T14:00:00Z")
    run_2 = schedule(1, "2026-08-03T14:00:00Z", "2026-08-03T22:00:00Z")
    run_3 = schedule(2, "2026-08-03T06:00:00Z", "2026-08-03T14:00:00Z")

    fx.set_clock(client, "2026-08-03T14:00:00Z")
    for run_id in (run_1, run_2, run_3):
        fx.start_melt(client, ctx["plant_id"], run_id)
        fx.start_cure(
            client,
            ctx["plant_id"],
            run_id,
            avg_zone_temp_f=470.0,
            line_speed_fpm=40.0,
            binder_applied_kg=900.0,
        )

    qe_alt = quality_engineer_headers(QUALITY_ENGINEER_USER_ID_ALT)

    def request(run_id: str, window_start: str, window_end: str) -> str:
        return fx.request_thermal_test(
            client,
            run_id,
            ctx["sku_id"],
            ctx["program_id"],
            window_start=window_start,
            window_end=window_end,
            user_id=QUALITY_ENGINEER_USER_ID_ALT,
        )["id"]

    test_1 = request(run_1, "2026-08-05T08:00:00Z", "2026-08-05T12:00:00Z")
    first = get_success_data(client.start_lab(test_1, qe_alt))
    test_2 = request(run_2, "2026-08-05T12:00:00Z", "2026-08-05T16:00:00Z")
    second = get_success_data(client.start_lab(test_2, qe_alt))
    test_3 = request(run_3, "2026-08-05T11:00:00Z", "2026-08-05T12:00:00Z")

    ctx.update(
        {
            "run_1": run_1,
            "run_2": run_2,
            "run_3": run_3,
            "test_1": test_1,
            "test_2": test_2,
            "test_3": test_3,
            "first": first,
            "second": second,
            "qe_alt": qe_alt,
        }
    )
    return ctx


def test_a_third_window_touching_one_slot_and_overlapping_another_is_refused(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "Count the thermal tests whose status is `IN_LAB`, whose
    `certification_program_id` matches this test's, and whose **closed** window from
    `window_start` to `window_end` intersects this test's closed window; that count must
    be strictly less than the program's `max_concurrent_lab_tests`."

    Design: Difficulty/resource_temporal_overlap/lab_capacity_is_aggregate_over_closed_windows_within_one_program
    """
    ctx = _three_curing_runs(client)
    # Two tests are individually legal: the second was admitted while touching the first
    # at 12:00:00, because 1 was still strictly less than 2.
    assert_field_equals(ctx["first"], "status", "IN_LAB")
    assert_field_equals(ctx["second"], "status", "IN_LAB")

    resp = client.start_lab(ctx["test_3"], ctx["qe_alt"])

    validate_error(resp, ApiErrors.LAB_CAPACITY_EXCEEDED)

    held = fx.get_thermal_test(client, ctx["test_3"])
    assert_field_equals(held, "status", "REQUESTED")
    assert_field_equals(held, "specimen_r_values", [])
    assert_field_equals(held, "attempt_number", 1)
    assert held["conformance_verdict"] is None


def test_completing_one_test_frees_the_slot_the_third_needed(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "Adjacency counts as an intersection, so a test whose window ends exactly
    where another begins occupies the lab alongside it."

    Design: Difficulty/resource_temporal_overlap/lab_capacity_is_aggregate_over_closed_windows_within_one_program
    """
    ctx = _three_curing_runs(client)
    validate_error(
        client.start_lab(ctx["test_3"], ctx["qe_alt"]),
        ApiErrors.LAB_CAPACITY_EXCEEDED,
    )

    finished = get_success_data(
        client.record_result(ctx["test_1"], CONFORMING_SPECIMENS, ctx["qe_alt"])
    )
    assert_field_equals(finished, "specimen_count", 3)
    assert_close(finished["min_r_value"], 12.90, 2, "min_r_value")
    assert_close(finished["mean_r_value"], 13.07, 2, "mean_r_value")
    assert_field_equals(finished, "conformance_verdict", "CONFORMING")
    assert_field_equals(finished, "status", "COMPLETED")
    # Completing one test leaves the other two runs' quality dimensions alone.
    assert_field_equals(fx.get_run(client, ctx["run_1"]), "qc_status", "CONFORMING")
    assert_field_equals(fx.get_run(client, ctx["run_2"]), "qc_status", "SAMPLED")
    assert_field_equals(fx.get_run(client, ctx["run_3"]), "qc_status", "SAMPLED")

    admitted = get_success_data(client.start_lab(ctx["test_3"], ctx["qe_alt"]))

    assert_field_equals(admitted, "status", "IN_LAB")
    # The refused attempt did not disturb the values pinned at request time.
    assert_field_equals(admitted, "conformance_basis", "PER_SPECIMEN")
    assert_close(admitted["declared_r_value_at_test"], 13.0, 2, "declared_r_value_at_test")
