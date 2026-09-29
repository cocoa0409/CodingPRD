"""Truck docks: the buffered separation each dock number insists on between
consecutive occupations, and the per-dock independence of that rule."""
from test_helpers import (
    ApiErrorId,
    draft_booking,
    place_hold,
    read_reservation,
    reserve_dock,
    setup_arena,
    validate_error,
    validate_paginated,
    TEST_USERS,
)

COORDINATOR = TEST_USERS["labor_coordinator_headers"]


def _one_show_with_two_loaded_docks():
    """An ice show whose load-in occupies docks two and three over the same four
    hours, leaving both docks free from 14:00 onwards."""
    arena = setup_arena(profiles=("ICE",))
    booking = draft_booking(
        arena["venue_id"], arena["profiles"]["ICE"]["id"], "Hockey Sep 9",
        "2026-09-09T00:00:00Z", "2026-09-09T03:00:00Z",
        expected_attendance=15_000, rigging_load_kg=3_000,
        promoter_name="Lakeside Hockey Club",
    )
    arena["booking"] = place_hold(booking["id"])
    arena["dock_two_load_in"] = reserve_dock(
        arena["booking"]["id"], 2, "LOAD_IN",
        "2026-09-09T10:00:00Z", "2026-09-09T14:00:00Z", truck_count=6,
    )
    arena["dock_three_load_in"] = reserve_dock(
        arena["booking"]["id"], 3, "LOAD_IN",
        "2026-09-09T10:00:00Z", "2026-09-09T14:00:00Z", truck_count=6,
    )
    return arena


class TestDockBufferSeparation:
    def test_a_gap_of_exactly_the_buffer_is_accepted_on_the_same_dock(self, api):
        """PRD §2.7: "A proposed dock window collides with an existing one when the proposed
        `window_start_utc` is strictly earlier than the existing `window_end_utc` advanced
        forward by `dock_buffer_minutes`, and simultaneously the existing `window_start_utc` is
        strictly earlier than the proposed `window_end_utc` advanced forward by
        `dock_buffer_minutes`."
        PRD §2.7: "A gap of exactly `dock_buffer_minutes` between two windows is therefore
        accepted."
        PRD §3.9: "Either a `ChangeoverSupervisor` or a `LaborCoordinator` reserves a window,
        supplying the `dock_number` to occupy, a `purpose` of either `LOAD_IN` or `LOAD_OUT`,
        the occupation's `window_start_utc` and `window_end_utc` with the end strictly after
        the start, and a `truck_count` between 1 and 60 for the trucks expected through in that
        window."
        PRD §3.9: "A reservation is created `RESERVED`; the only other state is `RELEASED`,
        which is terminal."

        Design: Difficulty/resource_temporal_overlap/dock_windows_accept_a_gap_of_exactly_the_buffer_and_reject_one_minute_less_on_the_same_dock
        """
        arena = _one_show_with_two_loaded_docks()
        accepted = reserve_dock(
            arena["booking"]["id"], 2, "LOAD_OUT",
            "2026-09-09T14:30:00Z", "2026-09-09T16:00:00Z", truck_count=4,
            headers=COORDINATOR,
        )

        assert accepted["status"] == "RESERVED"
        assert accepted["dock_number"] == 2
        assert accepted["purpose"] == "LOAD_OUT"
        assert accepted["window_start_utc"] == "2026-09-09T14:30:00.000Z"
        assert accepted["window_end_utc"] == "2026-09-09T16:00:00.000Z"
        assert accepted["truck_count"] == 4
        assert accepted["release_reason"] is None

        assert read_reservation(
            arena["booking"]["id"], arena["dock_two_load_in"]["id"]
        )["status"] == "RESERVED"

    def test_one_minute_less_than_the_buffer_collides_on_the_neighbouring_dock(
        self, api
    ):
        """PRD §2.7: "A proposed dock window collides with an existing one when the proposed
        `window_start_utc` is strictly earlier than the existing `window_end_utc` advanced
        forward by `dock_buffer_minutes`, and simultaneously the existing `window_start_utc` is
        strictly earlier than the proposed `window_end_utc` advanced forward by
        `dock_buffer_minutes`."
        PRD §3.9: "The collision test then runs *before* the dock-number range test, so a
        request that names both an out-of-range dock and a colliding window reports the
        collision: no other reservation on the same arena and the same `dock_number` whose
        `status` is `RESERVED` may collide under the buffered half-open convention of §2.7, and
        a collision is `ERR_DOCK_WINDOW_CONFLICT`."
        PRD §3.9: "A booking's reservations are listed through a reverse-reachability read that
        can be narrowed by `purpose` and by `status`."

        Design: Difficulty/resource_temporal_overlap/dock_windows_accept_a_gap_of_exactly_the_buffer_and_reject_one_minute_less_on_the_same_dock
        """
        arena = _one_show_with_two_loaded_docks()
        reserve_dock(
            arena["booking"]["id"], 2, "LOAD_OUT",
            "2026-09-09T14:30:00Z", "2026-09-09T16:00:00Z", truck_count=4,
            headers=COORDINATOR,
        )

        response = api.create_dock_slot_reservation(
            arena["booking"]["id"],
            {
                "dock_number": 3,
                "purpose": "LOAD_OUT",
                "window_start_utc": "2026-09-09T14:29:00Z",
                "window_end_utc": "2026-09-09T16:00:00Z",
                "truck_count": 4,
            },
            COORDINATOR,
        )
        validate_error(response, ApiErrorId.ERR_DOCK_WINDOW_CONFLICT.value, 409)

        assert read_reservation(
            arena["booking"]["id"], arena["dock_three_load_in"]["id"]
        )["status"] == "RESERVED"

        rows, meta = validate_paginated(
            api.list_dock_slot_reservations(arena["booking"]["id"], COORDINATOR)
        )
        assert meta["total_count"] == 3, (
            "the two load-ins and the one accepted load-out, and nothing else"
        )
        assert all(row["status"] == "RESERVED" for row in rows)
