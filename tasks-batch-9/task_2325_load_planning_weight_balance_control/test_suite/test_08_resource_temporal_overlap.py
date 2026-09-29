"""Two resources booked over intervals with deliberately opposite edge semantics."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import ADMIN, LOAD_CONTROLLER, api_client
from test_helpers import ApiErrorId as E
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx


def _rotation(world: fx.Scenario, aircraft_id: str, flight_number: str, off_block: str, on_block: str):
    return api_client.create_flight(
        F.flight_payload(
            aircraft_id,
            world.runway_id,
            world.program_id,
            flight_number=flight_number,
            scheduled_off_block_utc=off_block,
            scheduled_on_block_utc=on_block,
        ),
        LOAD_CONTROLLER,
    )


# ---------------------------------------------------------------------------
# The airframe: a closed occupancy interval with a trailing buffer
# ---------------------------------------------------------------------------


def _occupied_airframe() -> fx.Scenario:
    """One airframe already occupied from 10:00 to 13:15 inclusive."""
    world = fx.reference_world(compartment_specs=[], band_specs=[F.CANONICAL_BANDS[1]])
    return fx.flight_world(world, flight_number="LX1720")


class TestAircraftOccupancyClosedInterval:
    def test_a_rotation_touching_the_buffer_endpoint_collides(self):
        """A departure exactly 45 minutes after the previous on-block is refused.

        PRD: "Intervals that merely touch at a single endpoint do collide;
        back-to-back rotations must therefore be separated by more than the
        buffer, not exactly by it."

        Design: Difficulty/resource_temporal_overlap/aircraft_occupancy_closed_interval_touching_collides
        """
        world = _occupied_airframe()

        response = _rotation(
            world,
            world.aircraft_id,
            "LX1722",
            "2026-08-15T13:15:00Z",
            "2026-08-15T15:45:00Z",
        )

        validate_error(response, E.AIRCRAFT_OCCUPANCY_CONFLICT, 409)

    def test_one_minute_past_the_buffer_is_admitted(self):
        """A single minute of separation beyond the buffer clears the airframe.

        PRD: "A flight occupies its airframe over a **closed** interval that begins
        at its off-block instant and ends 45 minutes — three quarters of an hour of
        turnaround buffer — after its on-block instant, inclusive at both ends."

        Design: Difficulty/resource_temporal_overlap/aircraft_occupancy_closed_interval_touching_collides
        """
        world = _occupied_airframe()
        validate_error(
            _rotation(
                world, world.aircraft_id, "LX1722",
                "2026-08-15T13:15:00Z", "2026-08-15T15:45:00Z",
            ),
            E.AIRCRAFT_OCCUPANCY_CONFLICT,
            409,
        )

        admitted = get_success_data(
            _rotation(
                world, world.aircraft_id, "LX1724",
                "2026-08-15T13:16:00Z", "2026-08-15T15:45:00Z",
            ),
            201,
        )

        A.assert_flight_state(admitted, status="PLANNING")

    def test_the_buffer_travels_with_each_newly_admitted_rotation(self):
        """The second rotation carries its own buffer and blocks 16:30 in turn.

        PRD: "A new flight is refused with `ERR_AIRCRAFT_OCCUPANCY_CONFLICT` when
        its occupancy interval shares at least one instant with the occupancy
        interval of any existing flight on the same airframe whose `status` is
        `PLANNING`, `LOAD_CONTROLLED` or `DEPARTED`."

        Design: Difficulty/resource_temporal_overlap/aircraft_occupancy_closed_interval_touching_collides
        """
        world = _occupied_airframe()
        validate_error(
            _rotation(
                world, world.aircraft_id, "LX1722",
                "2026-08-15T13:15:00Z", "2026-08-15T15:45:00Z",
            ),
            E.AIRCRAFT_OCCUPANCY_CONFLICT,
            409,
        )
        get_success_data(
            _rotation(
                world, world.aircraft_id, "LX1724",
                "2026-08-15T13:16:00Z", "2026-08-15T15:45:00Z",
            ),
            201,
        )

        validate_error(
            _rotation(
                world, world.aircraft_id, "LX1726",
                "2026-08-15T16:30:00Z", "2026-08-15T18:00:00Z",
            ),
            E.AIRCRAFT_OCCUPANCY_CONFLICT,
            409,
        )
        last = get_success_data(
            _rotation(
                world, world.aircraft_id, "LX1728",
                "2026-08-15T16:31:00Z", "2026-08-15T18:00:00Z",
            ),
            201,
        )

        A.assert_flight_state(last, status="PLANNING")
        A.assert_flight_capacity(
            last, allowed_payload_kg=20180.00, limiting_factor="MZFW"
        )
        rows, meta = validate_paginated(
            api_client.list_flights(LOAD_CONTROLLER, {"aircraft_id": world.aircraft_id})
        )
        A.assert_pagination_meta(meta, total_count=3)


# ---------------------------------------------------------------------------
# The runway: a half-open departure window with an aggregate capacity
# ---------------------------------------------------------------------------


def _full_slot_window():
    """Three airframes, two of which already share the [10:00, 10:10) window."""
    first = fx.reference_world(compartment_specs=[], band_specs=[F.CANONICAL_BANDS[1]])
    second = fx.sibling_airframe_world(first, registration="HB-BBB", compartment_specs=[])
    third = fx.sibling_airframe_world(first, registration="HB-CCC", compartment_specs=[])

    early = get_success_data(
        _rotation(
            first, first.aircraft_id, "LX1730",
            "2026-08-15T10:00:00Z", "2026-08-15T10:20:00Z",
        ),
        201,
    )
    get_success_data(
        _rotation(
            first, second.aircraft_id, "LX1732",
            "2026-08-15T10:05:00Z", "2026-08-15T10:25:00Z",
        ),
        201,
    )
    return first, third, early


def _late_window_attempt(world: fx.Scenario, aircraft_id: str, flight_number: str, off_block: str):
    return _rotation(world, aircraft_id, flight_number, off_block, "2026-08-15T11:00:00Z")


class TestRunwaySlotHalfOpenWindow:
    def test_the_last_second_of_the_window_is_still_inside_it(self):
        """At 10:09:59 the window is still full and the departure is refused.

        PRD: "A departure at some instant belongs to the window that begins at
        that instant floored down to the nearest 10-minute boundary measured from
        the top of the hour, and that window is **half-open**: it includes its own
        start instant and excludes the instant exactly 10 minutes later."

        Design: Difficulty/resource_temporal_overlap/runway_slot_half_open_window_aggregate_capacity
        """
        world, third, _ = _full_slot_window()

        response = _late_window_attempt(
            world, third.aircraft_id, "LX1734", "2026-08-15T10:09:59Z"
        )

        validate_error(response, E.RUNWAY_SLOT_FULL, 409)

    def test_the_next_boundary_instant_belongs_to_the_following_window(self):
        """At 10:10:00 the departure has moved on to an empty window.

        PRD: "A departure standing exactly on the next 10-minute boundary belongs
        to the following window and never collides with the current one."

        Design: Difficulty/resource_temporal_overlap/runway_slot_half_open_window_aggregate_capacity
        """
        world, third, _ = _full_slot_window()
        validate_error(
            _late_window_attempt(
                world, third.aircraft_id, "LX1734", "2026-08-15T10:09:59Z"
            ),
            E.RUNWAY_SLOT_FULL,
            409,
        )

        admitted = get_success_data(
            _late_window_attempt(
                world, third.aircraft_id, "LX1736", "2026-08-15T10:10:00Z"
            ),
            201,
        )

        A.assert_flight_state(admitted, status="PLANNING")

    def test_cancelling_a_flight_releases_its_slot_back_into_the_window(self):
        """The count filters on status, so a cancelled departure frees its slot.

        PRD: "A new flight is refused with `ERR_RUNWAY_SLOT_FULL` when the number
        of existing flights on the same `departure_runway_id`, with `status`
        `PLANNING`, `LOAD_CONTROLLED` or `DEPARTED`, whose
        `scheduled_off_block_utc` falls inside that same window, already equals the
        runway's `slot_capacity_per_window`."

        Design: Difficulty/resource_temporal_overlap/runway_slot_half_open_window_aggregate_capacity
        """
        world, third, early = _full_slot_window()
        validate_error(
            _late_window_attempt(
                world, third.aircraft_id, "LX1734", "2026-08-15T10:09:59Z"
            ),
            E.RUNWAY_SLOT_FULL,
            409,
        )
        next_window = get_success_data(
            _late_window_attempt(
                world, third.aircraft_id, "LX1736", "2026-08-15T10:10:00Z"
            ),
            201,
        )

        for flight_id in (str(next_window["id"]), str(early["id"])):
            cancelled = get_success_data(api_client.cancel_flight(flight_id, ADMIN), 200)
            A.assert_flight_state(cancelled, status="CANCELLED")

        readmitted = get_success_data(
            _late_window_attempt(
                world, third.aircraft_id, "LX1738", "2026-08-15T10:09:59Z"
            ),
            201,
        )
        A.assert_flight_state(readmitted, status="PLANNING")
        A.assert_flight_capacity(
            readmitted, allowed_payload_kg=20180.00, limiting_factor="MZFW"
        )
        rows, meta = validate_paginated(
            api_client.list_flights(
                LOAD_CONTROLLER, {"departure_runway_id": world.runway_id}
            )
        )
        A.assert_pagination_meta(meta, total_count=4)
        rows, meta = validate_paginated(
            api_client.list_flights(LOAD_CONTROLLER, {"status": "CANCELLED"})
        )
        A.assert_pagination_meta(meta, total_count=2)
