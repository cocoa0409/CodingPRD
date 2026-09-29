"""
Two window rules with deliberately opposite geometry.

Shaft time is half-open and additive: windows that merely touch never overlap, and
overlapping windows are legal right up to the moment their summed hourly rates pass
the shaft's throughput. Loadout-bay time is closed and exclusive: one shipment at a
time, padded on both sides by the larger of the two modes' buffers, so a single
minute decides whether a truck may follow a train.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_HOIST_CAPACITY_EXCEEDED,
    ERR_LOADOUT_BAY_CONFLICT,
)
from test_helpers.assertions import assert_lot_tonnage, assert_rate_per_hour, assert_tons
from test_helpers.constants import (
    COARSE,
    COVERED,
    HIGHWAY_DEICING,
    MODE_RAIL,
    MODE_TRUCK,
    RUN_SCHEDULED,
    SHIPMENT_PLANNED,
)
from test_helpers.test_users import LOGISTICS, MINE_PLANNER

CLOCK = "2026-08-10T00:00:00Z"


def _mine_with_two_touching_hoist_windows(api):
    """
    A 24000 t/day shaft — exactly 1000.00 t/h — carrying two 6000 t runs booked over
    [00:00, 06:00) and [06:00, 12:00) of the following day. Each run is sized at the
    full hourly capacity, so only the half-open geometry lets the pair coexist.
    """
    fx.set_clock(api, CLOCK)
    mine = fx.create_mine(api, name="Retsof", rated_hoist_tons_per_day=24000)
    panel = fx.create_panel(
        api, mine["id"], panel_code="P-1", pillar_recovery_allowed=True
    )
    fx.develop(api, panel["id"])
    fx.start_production(api, panel["id"])

    first = fx.create_run(
        api,
        mine["id"],
        panel["id"],
        planned_tons=6000,
        hoist_window_start="2026-08-11T00:00:00Z",
        hoist_window_end="2026-08-11T06:00:00Z",
    )
    second = fx.create_run(
        api,
        mine["id"],
        panel["id"],
        planned_tons=6000,
        hoist_window_start="2026-08-11T06:00:00Z",
        hoist_window_end="2026-08-11T12:00:00Z",
    )
    return {
        "mine": fx.refresh_mine(api, mine["id"]),
        "panel": panel,
        "first": first,
        "second": second,
    }


def test_touching_hoist_windows_both_ride_the_ceiling_but_a_one_hour_lap_does_not(api):
    """
    Two runs at exactly 1000.0000 t/h are both accepted, which can only happen if the
    endpoint they share is not an overlap and if a peak equal to capacity is allowed.
    A third run at the same rate, lapping the first by a single hour, peaks at
    2000.0000 t/h and is refused.

    PRD §3.4: "From the window the server derives `planned_tons_per_hour`: the run's
    `planned_tons` divided by the exact length of the window in hours (which may be
    fractional), rounded half up to four decimal places."

    PRD §3.4: "Windows here are **half-open**: a window covers its start instant and
    every instant up to but not including its end, so two windows that merely touch —
    one ending exactly where the next begins — do not overlap."

    PRD §3.4: "Sort the events by timestamp ascending. Where two events share a
    timestamp, apply every decrease before any increase — this tie-break is precisely
    what makes touching windows non-overlapping."

    PRD §3.4: "The request is refused with `ERR_HOIST_CAPACITY_EXCEEDED` only when the
    peak is **strictly greater** than the capacity. A peak exactly equal to capacity is
    accepted."

    Design: Difficulty/resource_temporal_overlap/half_open_hoist_windows_touch_and_aggregate_rate_equals_capacity
    """
    world = _mine_with_two_touching_hoist_windows(api)
    mine = world["mine"]

    # 24000 t/day undivided by any derate: the hourly ceiling is exactly 1000.00 t/h.
    assert_tons(
        mine["effective_hoist_tons_per_day"], 24000.00, "effective_hoist_tons_per_day"
    )
    assert_rate_per_hour(world["first"]["planned_tons_per_hour"], 1000.0000)
    assert_rate_per_hour(world["second"]["planned_tons_per_hour"], 1000.0000)
    assert world["first"]["status"] == RUN_SCHEDULED
    assert world["second"]["status"] == RUN_SCHEDULED
    assert_tons(mine["scheduled_hoist_tons_open"], 12000.00, "scheduled_hoist_tons_open")

    lapped = api.create_run(
        f.run_payload(
            mine["id"],
            world["panel"]["id"],
            mine["version"],
            planned_tons=6000,
            hoist_window_start="2026-08-11T05:00:00Z",
            hoist_window_end="2026-08-11T11:00:00Z",
        ),
        MINE_PLANNER,
    )
    validate_error(lapped, ERR_HOIST_CAPACITY_EXCEEDED, 409)

    after = fx.refresh_mine(api, mine["id"])
    assert_tons(after["scheduled_hoist_tons_open"], 12000.00, "scheduled_hoist_tons_open")
    assert after["version"] == mine["version"]
    assert len(fx.runs_of_mine(api, mine["id"])) == 2


def test_two_concurrent_half_rate_runs_sum_to_the_ceiling_and_ten_more_tonnes_break_it(
    api,
):
    """
    The rule is a sum, not a ban on overlap: two genuinely concurrent runs at
    500.0000 t/h each share three hours of shaft time legally, and a third run over
    that same span at a mere 10.0000 t/h is refused because 1010.0000 is strictly
    greater than the ceiling.

    PRD §3.4: "Overlap itself is not forbidden; what is forbidden is exceeding the
    shaft's throughput while overlapping."

    PRD §3.4: "Sweep the sorted events, carrying a running total of the concurrent
    hourly rate, and take the maximum value that total reaches at any instant that lies
    inside the candidate's own window."

    PRD §3.4: "Compare the peak concurrent rate against the mine's hourly capacity —
    its `effective_hoist_tons_per_day` divided by 24, unrounded."

    PRD §2.7: "`planned_tons_per_hour` on a production run is carried at **4 decimal
    places**, round half up, and the aggregate hoist-capacity comparison is made on
    those 4-decimal rates."

    Design: Difficulty/resource_temporal_overlap/half_open_hoist_windows_touch_and_aggregate_rate_equals_capacity
    """
    world = _mine_with_two_touching_hoist_windows(api)
    mine_id = world["mine"]["id"]
    panel_id = world["panel"]["id"]

    third = fx.create_run(
        api,
        mine_id,
        panel_id,
        planned_tons=3000,
        hoist_window_start="2026-08-11T12:00:00Z",
        hoist_window_end="2026-08-11T18:00:00Z",
    )
    fourth = fx.create_run(
        api,
        mine_id,
        panel_id,
        planned_tons=3000,
        hoist_window_start="2026-08-11T15:00:00Z",
        hoist_window_end="2026-08-11T21:00:00Z",
    )
    assert_rate_per_hour(third["planned_tons_per_hour"], 500.0000)
    assert_rate_per_hour(fourth["planned_tons_per_hour"], 500.0000)
    assert fourth["status"] == RUN_SCHEDULED

    booked = fx.refresh_mine(api, mine_id)
    assert_tons(
        booked["scheduled_hoist_tons_open"], 18000.00, "scheduled_hoist_tons_open"
    )

    # 60 t over the same six hours is 10.0000 t/h, which tips [15:00, 18:00) to
    # 1010.0000 t/h.
    straw = api.create_run(
        f.run_payload(
            mine_id,
            panel_id,
            booked["version"],
            planned_tons=60,
            hoist_window_start="2026-08-11T15:00:00Z",
            hoist_window_end="2026-08-11T21:00:00Z",
        ),
        MINE_PLANNER,
    )
    validate_error(straw, ERR_HOIST_CAPACITY_EXCEEDED, 409)

    after = fx.refresh_mine(api, mine_id)
    assert_tons(after["scheduled_hoist_tons_open"], 18000.00, "scheduled_hoist_tons_open")
    assert after["version"] == booked["version"]
    scheduled = fx.runs_of_mine(api, mine_id, status=RUN_SCHEDULED)
    assert len(scheduled) == 4, f"expected four scheduled runs, got {len(scheduled)}"


def _depot_with_a_rail_booking(api):
    """
    One 5527.20 t covered highway-deicing lot at Depot A, a second depot to move it
    to, and a rail shipment holding the bay over the closed window
    [08:00, 10:00] with the 45-minute switching gap its mode demands.
    """
    fx.set_clock(api, CLOCK)
    world = fx.lot_at_depot(
        api,
        mine_kwargs=dict(name="Retsof", rated_hoist_tons_per_day=24000),
        panel_kwargs=dict(panel_code="P-1", pillar_recovery_allowed=True),
        depot_kwargs=dict(name="Depot A", outbound_freight_rate_per_ton=4.00),
        run_kwargs=dict(
            planned_tons=6000,
            hoist_window_start="2026-08-11T00:00:00Z",
            hoist_window_end="2026-08-11T06:00:00Z",
        ),
        hoisted_tons=6000,
        product_line=HIGHWAY_DEICING,
        screen_spec=COARSE,
        anticaking_ppm=30,
        input_tons=6000,
        moisture_pct=2.0,
        storage_kind=COVERED,
    )
    assert_tons(world["lot"]["tons_available"], 5527.20, "tons_available")

    world["destination"] = fx.create_depot(
        api, name="Depot B", outbound_freight_rate_per_ton=5.00
    )
    world["rail"] = fx.create_shipment(
        api,
        world["lot"]["id"],
        world["depot"]["id"],
        world["destination"]["id"],
        1000,
        mode=MODE_RAIL,
        load_window_start="2026-08-12T08:00:00Z",
        load_window_end="2026-08-12T10:00:00Z",
        destination_storage_kind=COVERED,
    )
    return world


def test_a_truck_inherits_the_rail_peers_gap_and_collides_on_the_blocked_edge(api):
    """
    The truck's own buffer is 0, yet the gap it must respect is the rail peer's 45
    minutes, so the bay is blocked through 10:45 and a booking that starts on exactly
    that instant collides. Both stored gap figures show the buffer is a per-shipment
    property of its own mode, not of the pair.

    PRD §3.7: "The `required_gap_minutes` field is server-set from the `mode` — 45
    minutes for `RAIL`, 20 for `BARGE`, 0 for `TRUCK` — and records the switching or
    mooring separation that mode demands around its own window."

    PRD §3.7: "Unlike the hoist windows of §3.4, bay windows are **closed** intervals —
    they include both endpoints — and the bay is strictly pairwise exclusive: no two
    shipments may share it at all, at any rate."

    PRD §3.7: "For each peer in that order, take the required gap as the **larger** of
    the new shipment's mode buffer and that peer's mode buffer. A truck booking beside a
    rail booking therefore still owes the full 45 minutes, because the rail move is the
    one that needs the room."

    PRD §3.7: "The new shipment collides with that peer when its `load_window_start` is
    at or before the end of the blocked region **and** its `load_window_end` is at or
    after the beginning of the blocked region. Both comparisons are inclusive, so a
    window that merely grazes the blocked region's edge does collide."

    Design: Difficulty/resource_temporal_overlap/closed_loadout_windows_collide_across_mode_switch_buffer_by_one_minute
    """
    world = _depot_with_a_rail_booking(api)
    rail = world["rail"]
    assert rail["status"] == SHIPMENT_PLANNED
    assert rail["required_gap_minutes"] == 45

    # 10:00 plus the inherited 45 minutes is 10:45, and the edge is inclusive.
    refused = api.create_shipment(
        f.shipment_payload(
            world["lot"]["id"],
            world["depot"]["id"],
            world["destination"]["id"],
            100,
            mode=MODE_TRUCK,
            load_window_start="2026-08-12T10:45:00Z",
            load_window_end="2026-08-12T12:45:00Z",
            destination_storage_kind=COVERED,
        ),
        LOGISTICS,
    )
    validate_error(refused, ERR_LOADOUT_BAY_CONFLICT, 409)

    rows = fx.list_rows(
        api.list_shipments(LOGISTICS, {"origin_depot_id": world["depot"]["id"], "limit": 100})
    )
    assert len(rows) == 1, f"a refused booking must write nothing, found {len(rows)}"
    assert rows[0]["id"] == rail["id"]


def test_one_minute_later_clears_the_bay_and_neither_booking_moves_any_tonnage(api):
    """
    The identical truck booking shifted by sixty seconds is accepted, so the whole
    difference between refusal and acceptance is one minute at the closed edge. Two
    shipments then sit on the same lot at once without touching its tonnage, because
    only loading takes salt out of the pile.

    PRD §3.7: "Gaps are whole minutes and window instants are compared at second
    resolution, so a window starting one second after a 45-minute rail blocked region
    ends is clear, while one starting exactly at its final instant is not."

    PRD §3.7: "A new shipment opens with `status` at `PLANNED`, `received_lot_id` null,
    and `version` at 1."

    PRD §3.7: "Loading takes the tonnage physically out of the origin pile: the lot's
    `tons_on_hand` and `tons_available` each fall by the shipment's `tons`,
    `tons_reserved` is untouched, the origin depot's stored-tonnage figures and
    `covered_utilization_pct` are recomputed, and a lot drained to exactly 0
    `tons_on_hand` with 0 `tons_reserved` moves `AVAILABLE → DEPLETED`."

    Design: Difficulty/resource_temporal_overlap/closed_loadout_windows_collide_across_mode_switch_buffer_by_one_minute
    """
    world = _depot_with_a_rail_booking(api)

    validate_error(
        api.create_shipment(
            f.shipment_payload(
                world["lot"]["id"],
                world["depot"]["id"],
                world["destination"]["id"],
                100,
                mode=MODE_TRUCK,
                load_window_start="2026-08-12T10:45:00Z",
                load_window_end="2026-08-12T12:45:00Z",
                destination_storage_kind=COVERED,
            ),
            LOGISTICS,
        ),
        ERR_LOADOUT_BAY_CONFLICT,
        409,
    )

    truck = get_success_data(
        api.create_shipment(
            f.shipment_payload(
                world["lot"]["id"],
                world["depot"]["id"],
                world["destination"]["id"],
                100,
                mode=MODE_TRUCK,
                load_window_start="2026-08-12T10:46:00Z",
                load_window_end="2026-08-12T12:46:00Z",
                destination_storage_kind=COVERED,
            ),
            LOGISTICS,
        ),
        201,
    )
    assert truck["status"] == SHIPMENT_PLANNED
    assert truck["required_gap_minutes"] == 0
    assert truck["received_lot_id"] is None
    assert truck["version"] == 1

    rows = fx.list_rows(
        api.list_shipments(
            LOGISTICS, {"origin_depot_id": world["depot"]["id"], "limit": 100}
        )
    )
    assert len(rows) == 2, f"expected the rail peer and the 10:46 truck, got {len(rows)}"
    assert {row["id"] for row in rows} == {world["rail"]["id"], truck["id"]}

    # Both are still PLANNED, so the pile is exactly as the quality-control pass left it.
    assert_lot_tonnage(fx.refresh_lot(api, world["lot"]["id"]), 5527.20, 0.00, 5527.20)
