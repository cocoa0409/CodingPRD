"""Room and gear temporal-overlap conflicts (Difficulty rules 7, 8, 9).

Covers the room half-open-plus-turnaround footprint, the gear aggregate-capacity overlap
with no buffer, confirm's dependence on room occupancy, and gear-unit conservation
across release.
"""
from test_helpers import (
    setup_studio_room_client,
    setup_gear_item,
    create_booking,
    pay_deposit,
    confirm,
    add_gear_rental,
    fresh_booking_version,
    api_client,
    TEST_USERS,
    make_client_headers,
    get_success_data,
    get_booking,
    get_gear_rental,
    validate_error,
    create_gear_rental_payload,
)

SM = TEST_USERS["studio_manager_headers"]


# =====================================================================
# Difficulty rule 7 — cross_entity_state_dependency:
#   confirm_depends_on_room_occupancy_state
# =====================================================================
# Difficulty rule 8 — resource_temporal_overlap:
#   room_overlap_with_turnaround_buffer
# =====================================================================
class TestRoomTurnaroundOverlap:
    """A new booking starting within the turnaround buffer of a CONFIRMED booking collides on
    confirm, even though raw [start,end) windows are disjoint."""

    def _setup_a_confirmed_b_held(self):
        studio, room, client = setup_studio_room_client(
            studio_overrides={"deposit_pct": 0.60},
            room_overrides={"hourly_rate_cents": 6000, "block_rate_cents": 40000,
                            "turnaround_minutes": 30},
        )
        booking_a = create_booking(studio, room, client,
                                   start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
        pay_deposit(booking_a, client, 14400)
        confirm(booking_a)
        # booking_b 12:45 -> 13:45 starts inside the 30-min buffer after A's 12:30 end
        booking_b = create_booking(studio, room, client,
                                   start_at="2026-07-10T12:45:00Z", end_at="2026-07-10T13:45:00Z")
        pay_deposit(booking_b, client, 3600)
        return studio, room, client, booking_a, booking_b

    def test_confirm_inside_turnaround_buffer_rejected(self):
        """PRD §3.2: "The confirmation additionally enforces that the room is free: the requested
        footprint [start_at, end_at + turnaround_minutes) must not overlap the footprint of any
        other booking on the same room whose schedule_status is CONFIRMED or IN_SESSION. A
        collision is rejected with ERR_ROOM_UNAVAILABLE."

        Design: Difficulty/resource_temporal_overlap/room_overlap_with_turnaround_buffer
        """
        studio, room, client, booking_a, booking_b = self._setup_a_confirmed_b_held()
        res = api_client.confirm_booking(booking_b["id"], SM)
        validate_error(res, "ERR_ROOM_UNAVAILABLE", expected_status=409)
        bk = get_booking(booking_b["id"])
        assert bk["schedule_status"] == "HELD", bk["schedule_status"]

    def test_booking_starting_at_buffer_end_does_not_collide(self):
        """PRD §2.9: "the occupancy footprint of a booking is not [start_at, end_at) but
        [start_at, end_at + turnaround_minutes). Two bookings on the same room conflict whenever
        those buffered intervals overlap."

        Design: Difficulty/resource_temporal_overlap/room_overlap_with_turnaround_buffer
        """
        studio, room, client = setup_studio_room_client(
            studio_overrides={"deposit_pct": 0.60},
            room_overrides={"hourly_rate_cents": 6000, "block_rate_cents": 40000,
                            "turnaround_minutes": 30},
        )
        booking_a = create_booking(studio, room, client,
                                   start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
        pay_deposit(booking_a, client, 14400)
        confirm(booking_a)
        # booking_b starts at exactly 13:00 == A.end 12:30 + 30-min buffer (buffer end exclusive)
        booking_b = create_booking(studio, room, client,
                                   start_at="2026-07-10T13:00:00Z", end_at="2026-07-10T14:00:00Z")
        pay_deposit(booking_b, client, 3600)
        confirmed_b = confirm(booking_b)
        assert confirmed_b["schedule_status"] == "CONFIRMED", confirmed_b["schedule_status"]

    def test_confirm_validity_depends_on_room_occupancy(self):
        """PRD §3.2: "The confirmation additionally enforces that the room is free: the requested
        footprint [start_at, end_at + turnaround_minutes) must not overlap the footprint of any
        other booking on the same room whose schedule_status is CONFIRMED or IN_SESSION. A
        collision is rejected with ERR_ROOM_UNAVAILABLE."

        Design: Difficulty/cross_entity_state_dependency/confirm_depends_on_room_occupancy_state
        """
        studio, room, client, booking_a, booking_b = self._setup_a_confirmed_b_held()
        res = api_client.confirm_booking(booking_b["id"], SM)
        validate_error(res, "ERR_ROOM_UNAVAILABLE", expected_status=409)

    def test_held_booking_does_not_block_confirm(self):
        """PRD §2.9: "it is checked only against bookings whose `schedule_status` is `CONFIRMED`
        or `IN_SESSION` — a merely `HELD` booking does not yet reserve the calendar."

        Design: Difficulty/cross_entity_state_dependency/confirm_depends_on_room_occupancy_state
        """
        studio, room, client = setup_studio_room_client(
            studio_overrides={"deposit_pct": 0.60},
            room_overrides={"hourly_rate_cents": 6000, "block_rate_cents": 40000,
                            "turnaround_minutes": 30},
        )
        # booking_a left HELD (not confirmed) — does not reserve the calendar
        create_booking(studio, room, client,
                       start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
        booking_b = create_booking(studio, room, client,
                                   start_at="2026-07-10T12:45:00Z", end_at="2026-07-10T13:45:00Z")
        pay_deposit(booking_b, client, 3600)
        confirmed_b = confirm(booking_b)
        assert confirmed_b["schedule_status"] == "CONFIRMED", confirmed_b["schedule_status"]


# =====================================================================
# Difficulty rule 8 — resource_temporal_overlap:
#   gear_capacity_aggregate_overlap_no_buffer
# =====================================================================
class TestGearCapacityOverlap:
    """Aggregate-capacity counting across overlapping booking windows, no turnaround buffer."""

    def _setup_two_units_reserved(self):
        studio, room, client = setup_studio_room_client(
            studio_overrides={"deposit_pct": 0.60},
            room_overrides={"hourly_rate_cents": 6000, "block_rate_cents": 40000},
        )
        gear = setup_gear_item(studio["id"], name="Vintage Pre", total_units=2, daily_rate_cents=1500)
        booking_a = create_booking(studio, room, client,
                                   start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
        add_gear_rental(booking_a, gear, 2, expected_version=booking_a["version"])
        booking_b = create_booking(studio, room, client,
                                   start_at="2026-07-10T10:00:00Z", end_at="2026-07-10T11:00:00Z")
        return studio, room, client, gear, booking_a, booking_b

    def test_overlapping_reserve_exceeding_total_units_rejected(self):
        """PRD §3.6: "A rental is refused with ERR_GEAR_UNAVAILABLE when the sum of units across
        all RESERVED rentals of the same GearItem whose booking windows overlap the new booking's
        window would exceed that item's total_units."

        Design: Difficulty/resource_temporal_overlap/gear_capacity_aggregate_overlap_no_buffer
        """
        studio, room, client, gear, booking_a, booking_b = self._setup_two_units_reserved()
        # booking_b (overlaps a) requests 1 unit; 2 reserved + 1 > total_units 2
        res = api_client.create_gear_rental(
            booking_b["id"],
            create_gear_rental_payload(gear["id"], 1, booking_b["version"]), SM)
        validate_error(res, "ERR_GEAR_UNAVAILABLE", expected_status=409)

    def test_capacity_freed_for_non_overlapping_window(self):
        """PRD §3.6: "A rental is refused with ERR_GEAR_UNAVAILABLE when the sum of units across
        all RESERVED rentals of the same GearItem whose booking windows overlap the new booking's
        window would exceed that item's total_units."

        Design: Difficulty/resource_temporal_overlap/gear_capacity_aggregate_overlap_no_buffer
        """
        studio, room, client, gear, booking_a, booking_b = self._setup_two_units_reserved()
        # A disjoint, non-overlapping booking should reserve freely against full capacity
        booking_c = create_booking(studio, room, client,
                                   start_at="2026-07-11T09:00:00Z", end_at="2026-07-11T11:00:00Z")
        rental = add_gear_rental(booking_c, gear, 2, expected_version=booking_c["version"])
        assert rental["status"] == "RESERVED", rental["status"]
        assert rental["units"] == 2, rental["units"]


# =====================================================================
# Difficulty rule 9 — compensating_invariant:
#   gear_release_conserves_available_units
# =====================================================================
class TestGearReleaseConservesUnits:
    """Reserving 2 units then releasing restores available units to total_units."""

    def _setup_reserve_then_release(self):
        studio, room, client = setup_studio_room_client(
            studio_overrides={"deposit_pct": 0.60},
            room_overrides={"hourly_rate_cents": 6000, "block_rate_cents": 40000},
        )
        gear = setup_gear_item(studio["id"], name="Vintage Pre", total_units=2, daily_rate_cents=1500)
        booking_a = create_booking(studio, room, client,
                                   start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
        rental = add_gear_rental(booking_a, gear, 2, expected_version=booking_a["version"])
        get_success_data(api_client.release_gear_rental(booking_a["id"], rental["id"], SM))
        booking_b = create_booking(studio, room, client,
                                   start_at="2026-07-10T10:00:00Z", end_at="2026-07-10T11:00:00Z")
        return studio, room, client, gear, booking_a, rental, booking_b

    def test_released_rental_status_is_released(self):
        """PRD §3.6: "A StudioManager may release a rental, moving it from RESERVED to RELEASED
        and freeing its reserved units, provided the parent booking has not reached COMPLETED".

        Design: Difficulty/compensating_invariant/gear_release_conserves_available_units
        """
        studio, room, client, gear, booking_a, rental, booking_b = self._setup_reserve_then_release()
        released = get_gear_rental(rental["id"])
        assert released["status"] == "RELEASED", released["status"]

    def test_freed_units_allow_fresh_full_reserve_on_overlap(self):
        """PRD §3.6: "A rental is refused with ERR_GEAR_UNAVAILABLE when the sum of units across
        all RESERVED rentals of the same GearItem whose booking windows overlap the new booking's
        window would exceed that item's total_units."

        Design: Difficulty/compensating_invariant/gear_release_conserves_available_units
        """
        studio, room, client, gear, booking_a, rental, booking_b = self._setup_reserve_then_release()
        # the released 2 units are fully restored -> overlapping booking_b reserves 2 successfully
        rental2 = add_gear_rental(booking_b, gear, 2, expected_version=booking_b["version"])
        assert rental2["status"] == "RESERVED", rental2["status"]
