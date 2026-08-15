"""Slot capacity snapshots, room-occupancy windows, the OPEN/FULL cycle,
reschedule OCC, and slot-list pagination."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_tour_slot,
    assign_and_confirm_lead,
    cancel_booking,
    confirm_booking,
    create_certified_docent,
    create_general_booking,
    create_route,
    create_rooms,
    create_slot,
    get_slot,
    normalize_timestamp,
    open_slot,
    reschedule_slot_payload,
    setup_active_route_no_script,
    setup_active_route_with_script,
    setup_open_slot,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["museum_admin_headers"]


class TestSlotCapacitySnapshot:

    def test_candlelight_capacity_min_rooms_minus_buffer_4(self):
        """PRD section 3.4: "It is the smallest `capacity_max` among all
        rooms on the route — every room in `room_ids` participates regardless
        of whether it is currently open, because room closure is enforced
        separately at slot-open time — minus a buffer determined by the
        route's `kind`: two seats for a `STANDARD` route, zero for a `SCHOOL`
        route, and four for a `CANDLELIGHT` route. If that subtraction would
        drop the figure below one, the capacity floors at one."

        Design: Difficulty/combinatorial_formula/slot_capacity_min_rooms_kind_buffer
        """
        rooms = create_rooms([
            {"name": "Hall", "floor": 1, "capacity_max": 20,
             "safety_max_party": 12, "collection_tier": "STANDARD"},
            {"name": "Silver Closet", "floor": 1, "capacity_max": 12,
             "safety_max_party": 10, "collection_tier": "HIGH_VALUE"},
            {"name": "Ballroom", "floor": 2, "capacity_max": 30,
             "safety_max_party": 20, "collection_tier": "STANDARD"},
        ])
        route = create_route([r["id"] for r in rooms], kind="CANDLELIGHT",
                             duration_minutes=90, base_price_cents=1000,
                             name="Candlelight Full House")
        route = api_client.activate_tour_route(route["id"], ADMIN)
        validate_success(route)
        resp = api_client.create_tour_slot(
            {"route_id": route.json()["data"]["id"],
             "start_at": "2026-09-01T19:00:00Z"}, ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_tour_slot(data)
        # min(20, 12, 30) - CANDLELIGHT buffer 4 = 12 - 4 = 8
        assert data["capacity"] == 8, (
            f"capacity must be min(20,12,30) - 4 = 8, got {data['capacity']}"
        )

    def test_standard_kind_buffer_2_proves_kind_branch(self):
        """PRD section 3.4: "It is the smallest `capacity_max` among all
        rooms on the route — every room in `room_ids` participates regardless
        of whether it is currently open, because room closure is enforced
        separately at slot-open time — minus a buffer determined by the
        route's `kind`: two seats for a `STANDARD` route, zero for a `SCHOOL`
        route, and four for a `CANDLELIGHT` route. If that subtraction would
        drop the figure below one, the capacity floors at one."

        Design: Difficulty/combinatorial_formula/slot_capacity_min_rooms_kind_buffer
        """
        rooms = create_rooms([
            {"name": "Hall", "floor": 1, "capacity_max": 20,
             "safety_max_party": 12, "collection_tier": "STANDARD"},
            {"name": "Silver Closet", "floor": 1, "capacity_max": 12,
             "safety_max_party": 10, "collection_tier": "HIGH_VALUE"},
            {"name": "Ballroom", "floor": 2, "capacity_max": 30,
             "safety_max_party": 20, "collection_tier": "STANDARD"},
        ])
        route = create_route([r["id"] for r in rooms], kind="STANDARD",
                             duration_minutes=90, base_price_cents=1000,
                             name="Standard Full House")
        route = api_client.activate_tour_route(route["id"], ADMIN)
        validate_success(route)
        resp = api_client.create_tour_slot(
            {"route_id": route.json()["data"]["id"],
             "start_at": "2026-09-01T19:00:00Z"}, ADMIN)
        data = validate_success(resp, expected_status=201)
        # min(20, 12, 30) - STANDARD buffer 2 = 12 - 2 = 10 (raw min is 12)
        assert data["capacity"] == 10, (
            f"STANDARD buffer must yield capacity 10 on the same rooms, "
            f"got {data['capacity']}"
        )


class TestRoomOccupancyHalfOpen:

    def test_touching_windows_do_not_conflict(self):
        """PRD section 3.4: "Two slots conflict exactly when their routes
        share at least one room and that room's occupancy windows overlap
        under half-open semantics: the windows overlap only when each
        window's start is strictly before the other window's end, and windows
        that merely touch — one ending exactly as the other begins — do not
        conflict."
        PRD section 3.4: "its `end_at` is computed as `start_at` plus the
        route's `duration_minutes`".

        Design: Difficulty/resource_temporal_overlap/room_occupancy_half_open
        """
        ctx = setup_active_route_no_script()
        create_slot(ctx["route_id"], start_at="2026-09-01T10:00:00Z")
        resp = api_client.create_tour_slot(
            {"route_id": ctx["route_id"], "start_at": "2026-09-01T11:00:00Z"},
            ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_tour_slot(data)
        assert normalize_timestamp(data["end_at"]) == "2026-09-01T12:00:00Z", (
            f"end_at must be start_at + duration_minutes, "
            f"got {data['end_at']}"
        )

    def test_one_minute_overlap_conflicts(self):
        """PRD section 3.4: "Two slots conflict exactly when their routes
        share at least one room and that room's occupancy windows overlap
        under half-open semantics: the windows overlap only when each
        window's start is strictly before the other window's end, and windows
        that merely touch — one ending exactly as the other begins — do not
        conflict."
        PRD section 3.4: "A genuine collision is rejected with
        `ERR_ROOM_OCCUPANCY_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/room_occupancy_half_open
        """
        ctx = setup_active_route_no_script()
        create_slot(ctx["route_id"], start_at="2026-09-01T10:00:00Z")
        resp = api_client.create_tour_slot(
            {"route_id": ctx["route_id"], "start_at": "2026-09-01T10:59:00Z"},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_ROOM_OCCUPANCY_CONFLICT)


class TestSlotFullOpenCycle:

    def test_last_seat_reservation_flips_slot_full(self):
        """PRD section 3.4: "From there the system manages the seat pool:
        when a booking creation or confirmation drives `seats_available` to
        exactly zero the slot flips from `OPEN` to `FULL`, and when a
        cancellation or expiry frees seats it flips back from `FULL` to
        `OPEN` — a cycle that may repeat any number of times, with
        `seats_available` never going negative."

        Design: Difficulty/non_linear_state_machine/slot_full_open_cycle
        """
        ctx = setup_open_slot(
            room_specs=[{"name": "Nursery", "floor": 2, "capacity_max": 5,
                         "safety_max_party": 4, "collection_tier": "STANDARD"}])
        assert ctx["slot"]["capacity"] == 3, (
            f"capacity must be 5 - 2 = 3, got {ctx['slot']['capacity']}"
        )
        booking = create_general_booking(ctx["slot_id"], 3, visitor_name="Trio")
        assert booking["status"] == "RESERVED"
        slot = get_slot(ctx["slot_id"])
        assert slot["seats_available"] == 0
        assert slot["status"] == "FULL", (
            f"taking the last seat must flip the slot to FULL, "
            f"got {slot['status']}"
        )

    def test_cancellation_reopens_full_slot(self):
        """PRD section 3.4: "From there the system manages the seat pool:
        when a booking creation or confirmation drives `seats_available` to
        exactly zero the slot flips from `OPEN` to `FULL`, and when a
        cancellation or expiry frees seats it flips back from `FULL` to
        `OPEN` — a cycle that may repeat any number of times, with
        `seats_available` never going negative."
        PRD section 3.6: "A `RESERVED` booking always refunds zero, as does
        any booking that paid zero, such as a solo member visit."

        Design: Difficulty/non_linear_state_machine/slot_full_open_cycle
        """
        ctx = setup_open_slot(
            room_specs=[{"name": "Nursery", "floor": 2, "capacity_max": 5,
                         "safety_max_party": 4, "collection_tier": "STANDARD"}])
        booking = create_general_booking(ctx["slot_id"], 3, visitor_name="Trio")
        assert get_slot(ctx["slot_id"])["status"] == "FULL"
        cancelled = cancel_booking(booking["id"])
        assert cancelled["refund_cents"] == 0, (
            f"a RESERVED booking must refund zero, "
            f"got {cancelled['refund_cents']}"
        )
        slot = get_slot(ctx["slot_id"])
        assert slot["status"] == "OPEN", (
            f"freeing the seats must flip the slot back to OPEN, "
            f"got {slot['status']}"
        )
        assert slot["seats_available"] == 3


class TestRescheduleOptimisticConcurrency:

    def test_reschedule_slot_with_stale_version_returns_412(self):
        """PRD section 2.4: "Rescheduling a tour slot requires
        `expected_slot_version`, matched against the slot's current
        `version`. A mismatch is likewise rejected with `ERR_STALE_VERSION`
        (HTTP 412), and the slot keeps its existing schedule."
        PRD section 3.4: "A successful reschedule recomputes `end_at` from
        the new start, re-runs the room-occupancy check against the new
        windows (`ERR_ROOM_OCCUPANCY_CONFLICT`), re-runs the
        thirty-minute-buffer overlap check for the docents already rostered
        on the slot (`ERR_SHIFT_OVERLAP`), and increments the slot's
        `version`."

        Design: Corner/cross_cutting_layers/reschedule_slot_with_stale_version_returns_412
        """
        ctx = setup_active_route_no_script()
        slot = create_slot(ctx["route_id"], start_at="2026-09-01T10:00:00Z")
        observed_version = slot["version"]
        assert observed_version == 1

        resp = api_client.reschedule_tour_slot(
            slot["id"],
            reschedule_slot_payload("2026-09-05T10:00:00Z", observed_version),
            ADMIN)
        data = validate_success(resp)
        assert normalize_timestamp(data["start_at"]) == "2026-09-05T10:00:00Z"
        assert data["version"] == observed_version + 1, (
            f"a successful reschedule must increment the slot's version, "
            f"got {data['version']} after {observed_version}"
        )

        resp = api_client.reschedule_tour_slot(
            slot["id"],
            reschedule_slot_payload("2026-09-06T10:00:00Z", observed_version),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        slot_after = get_slot(slot["id"])
        assert normalize_timestamp(slot_after["start_at"]) \
            == "2026-09-05T10:00:00Z", (
                "a stale reschedule must leave the existing schedule in "
                f"place, got {slot_after['start_at']}"
            )


class TestRouteSlotPagination:

    def test_pagination_limit_offset_on_route_slots(self):
        """PRD section 2.3: "List endpoints accept two query parameters:
        `limit`, defaulting to 10 with a minimum of 1 and a maximum of 100,
        and `offset`, defaulting to 0. List responses report `limit`,
        `offset`, `total_count`, and `has_more` inside `meta`."

        Design: Corner/endpoints/pagination_limit_offset_on_route_slots
        """
        ctx = setup_active_route_no_script()
        create_slot(ctx["route_id"], start_at="2026-09-01T10:00:00Z")
        create_slot(ctx["route_id"], start_at="2026-09-01T12:00:00Z")
        create_slot(ctx["route_id"], start_at="2026-09-01T14:00:00Z")

        resp = api_client.list_route_tour_slots(
            ctx["route_id"], ADMIN, params={"limit": 2})
        page1, meta1 = validate_paginated(resp)
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(page1) == 2

        resp = api_client.list_route_tour_slots(
            ctx["route_id"], ADMIN, params={"limit": 2, "offset": 2})
        page2, meta2 = validate_paginated(resp)
        assert len(page2) == 1
        assert meta2["has_more"] is False
