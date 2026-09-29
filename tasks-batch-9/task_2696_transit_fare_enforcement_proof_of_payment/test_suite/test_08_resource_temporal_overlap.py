"""
Two contended resources with deliberately opposite interval conventions: the
line collision rule is half-open, the zone capacity rule is closed.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_DEPLOYMENT_WINDOW_OVERLAP,
    ERR_ZONE_DEPLOYMENT_CAPACITY,
)
from test_helpers.assertions import assert_instant_equals, assert_rate_equals
from test_helpers.constants import (
    DEPLOYMENT_STATUS_PLANNED,
    MODE_BUS,
    MODE_STREETCAR,
    SAMPLING_CLUSTER_RANDOM,
    ZONE_STATUS_DESIGNATED,
)
from test_helpers.test_users import PLANNER_HEADERS

WINDOW_START = "2026-08-05T06:00:00Z"
WINDOW_END = "2026-08-05T14:00:00Z"


def _plan_request(api, line_id, zone_id, window_start, window_end, **overrides):
    payload = factories.deployment_payload(
        line_id=line_id,
        zone_id=zone_id,
        window_start=window_start,
        window_end=window_end,
        planned_inspector_count=overrides.get("planned_inspector_count", 2),
        sampling_method=overrides.get("sampling_method", SAMPLING_CLUSTER_RANDOM),
        target_sample_size=overrides.get("target_sample_size", 4),
    )
    return api.create_inspection_deployment(payload, PLANNER_HEADERS)


# ── The line rule: half-open, so adjacency is legal ──────────────────

def _one_planned_deployment_in_a_roomy_zone(api):
    """
    A single planned deployment on a line inside a zone whose concurrency cap is
    wide enough that only the line rule can fire.
    """
    env = fixtures.build_environment(
        api, max_concurrent_deployments=4, clock_start="2026-08-01T00:00:00Z"
    )
    fixtures.move_clock(api, "2026-08-01T02:00:00Z")
    first = fixtures.plan_deployment(
        api,
        env["line"]["id"],
        env["zone"]["id"],
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        planned_inspector_count=3,
        target_sample_size=5,
    )
    return env, first


def test_a_window_starting_where_the_last_one_ended_is_accepted(api):
    """
    Because both windows are half-open, adjacency is permitted — a deployment
    ending at 14:00 and another starting at 14:00 do not collide — so the
    adjacent window is planned and the first deployment is untouched.

    Design: Difficulty/resource_temporal_overlap/line_deployment_windows_are_half_open_so_adjacent_windows_are_allowed
    """
    env, first = _one_planned_deployment_in_a_roomy_zone(api)

    adjacent = validate_success(
        _plan_request(
            api, env["line"]["id"], env["zone"]["id"], WINDOW_END, "2026-08-05T18:00:00Z"
        ),
        201,
    )
    assert_instant_equals(adjacent["window_start"], WINDOW_END, "adjacent.window_start")
    assert adjacent["status"] == DEPLOYMENT_STATUS_PLANNED
    assert adjacent["target_sample_size"] == 4
    assert_rate_equals(adjacent["sample_adequacy_ratio"], 0.0000, "sample_adequacy_ratio")

    untouched = fixtures.read_deployment(api, first["id"])
    assert_instant_equals(untouched["window_end"], WINDOW_END, "untouched.window_end")
    assert untouched["status"] == DEPLOYMENT_STATUS_PLANNED


def test_a_window_that_straddles_the_boundary_collides_on_the_line(api):
    """
    Where any other live deployment on the same `line_id` has a half-open window
    that shares an instant with the requested one the request is refused with
    `ERR_DEPLOYMENT_WINDOW_OVERLAP`, and the rejected window leaves no row.

    Design: Difficulty/resource_temporal_overlap/line_deployment_windows_are_half_open_so_adjacent_windows_are_allowed
    """
    env, _first = _one_planned_deployment_in_a_roomy_zone(api)
    line_id = env["line"]["id"]
    fixtures.get_success_data(
        _plan_request(api, line_id, env["zone"]["id"], WINDOW_END, "2026-08-05T18:00:00Z")
    )

    validate_error(
        _plan_request(
            api,
            line_id,
            env["zone"]["id"],
            "2026-08-05T13:00:00Z",
            "2026-08-05T15:00:00Z",
        ),
        ERR_DEPLOYMENT_WINDOW_OVERLAP,
        409,
    )

    rows, meta = validate_paginated(api.list_deployments(PLANNER_HEADERS, {"line_id": line_id}))
    assert meta["total_count"] == 2
    assert "2026-08-05T13:00:00Z" not in [row["window_start"] for row in rows]


# ── The zone rule: closed, so touching consumes a slot ───────────────

def _zone_at_capacity_two_with_three_lines(api):
    """
    A zone capped at two concurrent deployments, carrying three assigned lines
    and two already-overlapping deployments on two of them.
    """
    env = fixtures.build_environment(api, max_concurrent_deployments=2)
    zone_id = env["zone"]["id"]
    second_line = fixtures.register_line(
        api, line_code="L2", mode=MODE_BUS, daily_boardings=21000, baseline_evasion_rate_bps=900
    )
    third_line = fixtures.register_line(
        api,
        line_code="L3",
        mode=MODE_STREETCAR,
        daily_boardings=9000,
        baseline_evasion_rate_bps=1200,
    )
    fixtures.assign_line(api, zone_id, second_line["id"], platform_segment_count=3)
    fixtures.assign_line(api, zone_id, third_line["id"], platform_segment_count=2)
    fixtures.move_clock(api, "2026-08-01T02:00:00Z")

    fixtures.plan_deployment(
        api,
        env["line"]["id"],
        zone_id,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        planned_inspector_count=3,
        target_sample_size=5,
    )
    fixtures.get_success_data(
        _plan_request(
            api, second_line["id"], zone_id, "2026-08-05T12:00:00Z", "2026-08-05T16:00:00Z"
        )
    )
    return env, third_line


def test_a_window_that_merely_touches_an_existing_one_consumes_a_slot(api):
    """
    The zone cap counts deployments whose window treated as a closed interval
    shares any instant with the requested window treated as a closed interval, so
    a window starting exactly at another's end instant is refused with
    `ERR_ZONE_DEPLOYMENT_CAPACITY` rather than by the same-line collision rule.

    Design: Difficulty/resource_temporal_overlap/zone_deployment_capacity_uses_closed_intervals_so_a_touching_window_consumes_a_slot
    """
    env, third_line = _zone_at_capacity_two_with_three_lines(api)

    response = _plan_request(
        api,
        third_line["id"],
        env["zone"]["id"],
        WINDOW_END,
        "2026-08-05T15:00:00Z",
        planned_inspector_count=1,
        target_sample_size=2,
    )
    validate_error(response, ERR_ZONE_DEPLOYMENT_CAPACITY, 409)
    assert response.json()["data"]["error_id"] != ERR_DEPLOYMENT_WINDOW_OVERLAP

    zone = fixtures.read_zone(api, env["zone"]["id"])
    assert zone["max_concurrent_deployments"] == 2
    assert zone["designation_status"] == ZONE_STATUS_DESIGNATED


def test_the_same_window_a_minute_later_clears_the_closed_interval(api):
    """
    Shifting the window one minute past the earlier deployment's end instant
    drops the intersection count below the cap, so the third deployment is
    planned and the rejected window left no row behind.

    Design: Difficulty/resource_temporal_overlap/zone_deployment_capacity_uses_closed_intervals_so_a_touching_window_consumes_a_slot
    """
    env, third_line = _zone_at_capacity_two_with_three_lines(api)
    zone_id = env["zone"]["id"]
    _plan_request(
        api,
        third_line["id"],
        zone_id,
        WINDOW_END,
        "2026-08-05T15:00:00Z",
        planned_inspector_count=1,
        target_sample_size=2,
    )

    accepted = validate_success(
        _plan_request(
            api,
            third_line["id"],
            zone_id,
            "2026-08-05T14:01:00Z",
            "2026-08-05T15:00:00Z",
            planned_inspector_count=1,
            target_sample_size=2,
        ),
        201,
    )
    assert_instant_equals(accepted["window_start"], "2026-08-05T14:01:00Z", "accepted.window_start")
    assert accepted["status"] == DEPLOYMENT_STATUS_PLANNED
    assert accepted["planned_inspector_count"] == 1

    rows, meta = validate_paginated(api.list_deployments(PLANNER_HEADERS, {"zone_id": zone_id}))
    assert meta["total_count"] == 3
    assert [row["window_start"] for row in rows].count(WINDOW_END) == 0
