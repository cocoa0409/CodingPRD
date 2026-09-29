"""
Two resources with opposite overlap regimes: the machine window, half-open and
widened by changeover on both sides, and the booth hold, closed at both ends and
counted as an aggregate over runs that are still alive.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U


def a_router_with_a_morning_and_an_afternoon_window(api, env):
    """
    Two booked hours on one router: 08:00 to 09:00 and 12:00 to 13:00 on the
    second of August.
    """
    env["res1"] = F.create_reservation(api, env["cnc1"], "2026-08-02T08:00:00Z",
                                       "2026-08-02T09:00:00Z")["id"]
    env["res2"] = F.create_reservation(api, env["cnc1"], "2026-08-02T12:00:00Z",
                                       "2026-08-02T13:00:00Z")["id"]
    return env


def test_a_window_that_overlaps_nothing_is_still_refused_by_the_changeover_buffer(api, one_cnc_station):
    """
    The request ends a quarter of an hour before the afternoon booking begins and
    so overlaps nothing at all in raw terms, yet the half hour of re-tooling
    pushes its right edge past that booking and the router refuses it.

    PRD: "A proposed window conflicts with an existing reservation on the same
    station whose status is `HELD` or `CONSUMED` when the proposed `starts_at`
    falls strictly before that reservation's `ends_at` advanced by the changeover
    minutes, and at the same time the proposed `ends_at` advanced by the
    changeover minutes falls strictly after that reservation's `starts_at`."

    Design: Difficulty/resource_temporal_overlap/station_half_open_window_widened_by_changeover_on_both_sides
    """
    env = a_router_with_a_morning_and_an_afternoon_window(api, one_cnc_station)

    validate_error(api.create_station_reservation({
        "station_id": env["cnc1"],
        "starts_at": "2026-08-02T11:00:00Z", "ends_at": "2026-08-02T11:45:00Z",
    }, U.MACHINIST_HEADERS), E.ERR_STATION_WINDOW_CONFLICT, 409)


def test_a_window_that_clears_both_neighbours_is_booked_and_billed_without_the_buffer(api, one_cnc_station):
    """
    A window that starts exactly on the morning booking's widened edge and ends
    far enough ahead of the afternoon one is accepted, and the router's ledger
    counts three real hours rather than inflating them with re-tooling time.

    PRD: "Changeover minutes widen the conflict window only. They are never added
    to a reservation's `duration_minutes` and are never billed as machine time."

    Design: Difficulty/resource_temporal_overlap/station_half_open_window_widened_by_changeover_on_both_sides
    """
    env = a_router_with_a_morning_and_an_afternoon_window(api, one_cnc_station)

    accepted = validate_success(api.create_station_reservation({
        "station_id": env["cnc1"],
        "starts_at": "2026-08-02T09:30:00Z", "ends_at": "2026-08-02T10:30:00Z",
    }, U.MACHINIST_HEADERS), 201)
    assert accepted["status"] == "HELD"
    assert accepted["duration_minutes"] == 60

    station = validate_success(api.get_station(env["cnc1"], U.MACHINIST_HEADERS))
    A.assert_station_minutes(station, total=180, held=180, consumed=0, released=0)

    booked, _ = validate_paginated(api.list_station_reservations(
        U.MACHINIST_HEADERS, {"station_id": env["cnc1"]}))
    assert len(booked) == 3


def two_nitro_instruments_and_one_single_slot_booth(api):
    """
    Two plain nitrocellulose builds cut from one spruce lot, both standing in
    assembly, sharing a booth with a single chemistry slot; the first is already
    spraying from noon on the second of August.
    """
    env = X.build_machine_shop(api)
    X.build_released_lot(api, env)
    X.build_billet(api, env)
    X.read_lot_version(api, env, key="lot1", version_key="lot_v2")
    X.build_billet(api, env, key="blt2", version_key="lot_v2",
                   billet_code="BLT-002", board_feet=30.00)

    for order_key, code, billet, component, res_a, res_b, day in (
        ("bo1", "ORD-N1", "blt1", "cmp1", "res1", "res2", "2026-08-02"),
        ("bo2", "ORD-N2", "blt2", "cmp2", "res3", "res4", "2026-08-03"),
    ):
        order = F.create_order(api, F.order_payload(
            order_code=code, model_code="OM45", base_price_cents=300000,
            is_custom_shop=False, artist_tier="NONE", finish_system="NITRO",
            promised_date="2026-11-01T00:00:00Z"), U.COORDINATOR_HEADERS)
        env[order_key] = order["id"]
        F.confirm_order(api, env[order_key], 100000, U.COORDINATOR_HEADERS)
        F.lock_options(api, env[order_key], U.COORDINATOR_HEADERS)
        F.release_components(api, env[order_key])
        X.build_component_accepted(api, env, component_key=component,
                                   billet_key=billet, order_key=order_key,
                                   res_a=res_a, res_b=res_b,
                                   cnc_starts=f"{day}T08:00:00Z",
                                   cnc_ends=f"{day}T09:00:00Z",
                                   hs_starts=f"{day}T10:00:00Z",
                                   hs_ends=f"{day}T11:00:00Z")
        env[f"{order_key}_v3"] = F.start_assembly(api, env[order_key])["version"]

    F.set_clock(api, "2026-08-02T12:00:00Z")
    env["clock"] = "2026-08-02T12:00:00Z"
    F.log_climate_reading(api, env["fb1"], 50.0, 21.0, U.FINISH_TECH_HEADERS)
    env["fr1"] = F.create_finish_run(api, env["bo1"], env["fb1"], env["bo1_v3"],
                                     finish_system="NITRO", coat_count=8)["id"]
    F.set_clock(api, "2026-08-02T14:00:00Z")
    env["clock"] = "2026-08-02T14:00:00Z"
    return env


def test_a_second_body_cannot_join_a_single_slot_booth_that_is_already_occupied(api):
    """
    The standing hold overlaps the requested one and the chemistry matches, so
    nothing but the slot count is left to refuse the booking, and the count is one
    plus one against a capacity of one.

    PRD: "Second, capacity: the count of non-terminal runs whose closed hold
    interval overlaps the new hold, plus one for the new run, must not exceed the
    booth's `capacity_slots`. Exceeding it is `ERR_BOOTH_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/booth_closed_hold_capacity_counts_only_currently_occupying_non_terminal_runs
    """
    env = two_nitro_instruments_and_one_single_slot_booth(api)

    booth = validate_success(api.get_storage_room(env["fb1"], U.FINISH_TECH_HEADERS))
    assert booth["capacity_slots"] == 1
    assert booth["occupied_slots"] == 1

    validate_error(api.create_finish_run({
        "build_order_id": env["bo2"], "booth_id": env["fb1"],
        "finish_system": "NITRO", "coat_count": 8,
        "expected_build_order_version": env["bo2_v3"],
    }, U.FINISH_TECH_HEADERS), E.ERR_BOOTH_CAPACITY_EXCEEDED, 409)


def test_condemning_the_incumbent_run_frees_the_slot_for_the_identical_request(api):
    """
    No timestamp changes, only the status of the run holding the booth: once it is
    condemned it stops occupying anything, and the request refused moments earlier
    is accepted with its own projection.

    PRD: "A non-terminal run whose projected hold has already elapsed occupies
    nothing at the present instant and cannot block a new booking whose window is
    disjoint from it; conversely, a booking is admitted or refused by the
    interval-overlap count above, not by comparing `occupied_slots` to
    `capacity_slots`."

    Design: Difficulty/resource_temporal_overlap/booth_closed_hold_capacity_counts_only_currently_occupying_non_terminal_runs
    """
    env = two_nitro_instruments_and_one_single_slot_booth(api)
    F.complete_spray(api, env["fr1"])
    rejected = F.reject_run(api, env["fr1"], "RUN_ABORTED", U.INSPECTOR_HEADERS)
    assert rejected["status"] == "REJECTED"

    booth = validate_success(api.get_storage_room(env["fb1"], U.FINISH_TECH_HEADERS))
    assert booth["occupied_slots"] == 0
    first = validate_success(api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert first["build_stage"] == "IN_ASSEMBLY"

    created = validate_success(api.create_finish_run({
        "build_order_id": env["bo2"], "booth_id": env["fb1"],
        "finish_system": "NITRO", "coat_count": 8,
        "expected_build_order_version": env["bo2_v3"],
    }, U.FINISH_TECH_HEADERS), 201)
    assert created["status"] == "SPRAYING"
    assert created["booth_hold_from"] == "2026-08-02T14:00:00Z"
    assert created["booth_hold_until"] == "2026-08-16T18:00:00Z"

    after = validate_success(api.get_storage_room(env["fb1"], U.FINISH_TECH_HEADERS))
    assert after["occupied_slots"] == 1
