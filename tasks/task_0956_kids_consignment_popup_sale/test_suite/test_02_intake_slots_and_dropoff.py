"""Drop-off slots, bookings, capacity boundaries, and item drop-off gating."""
import pytest

from test_helpers import (
    ApiErrorId,
    book_and_check_in,
    book_slot,
    check_in_booking,
    create_event,
    create_item_for,
    create_slot,
    drop_off_item,
    get_item,
    get_slot,
    make_consignor_headers,
    open_intake,
    register_consignor,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSlotCapacityBoundary:

    def test_booking_reaching_exact_capacity_allowed(self, api, organizer_headers):
        """PRD §3.4: "Capacity is aggregate, not pairwise: a slot's `booked_count` counts its bookings in `BOOKED` or `CHECKED_IN` status, and a new booking is rejected with `ERR_SLOT_FULL` only when the slot's `booked_count` already equals its `capacity` — the booking that would bring the count exactly up to capacity is allowed, and the next one fails."

        Design: Difficulty/boundary_precision_check/slot_capacity_full_at_equality
        """
        event = create_event()
        open_intake(event["id"])
        slot = create_slot(event["id"], capacity=2)
        c1 = register_consignor(event["id"], "P1")
        c2 = register_consignor(event["id"], "P2")

        b1 = book_slot(slot["id"], c1["id"])
        b2 = book_slot(slot["id"], c2["id"])
        assert b1["status"] == "BOOKED" and b2["status"] == "BOOKED"
        slot_after = get_slot(slot["id"])
        assert slot_after["booked_count"] == 2, (
            f"The booking bringing booked_count exactly to capacity must be allowed; "
            f"booked_count={slot_after['booked_count']}"
        )

    def test_booking_beyond_capacity_rejected_slot_full(self, api, organizer_headers):
        """PRD §3.4: "a new booking is rejected with `ERR_SLOT_FULL` only when the slot's `booked_count` already equals its `capacity` — the booking that would bring the count exactly up to capacity is allowed, and the next one fails."

        Design: Difficulty/boundary_precision_check/slot_capacity_full_at_equality
        """
        event = create_event()
        open_intake(event["id"])
        slot = create_slot(event["id"], capacity=2)
        c1 = register_consignor(event["id"], "P1")
        c2 = register_consignor(event["id"], "P2")
        c3 = register_consignor(event["id"], "P3")
        book_slot(slot["id"], c1["id"])
        book_slot(slot["id"], c2["id"])

        resp = api.create_drop_off_booking(
            {"slot_id": slot["id"], "consignor_id": c3["id"]},
            make_consignor_headers(c3["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_FULL)
        assert get_slot(slot["id"])["booked_count"] == 2, (
            "booked_count must not drift after a rejected booking"
        )


class TestSlotAggregateCapacity:

    def test_same_window_bookings_coexist(self, api, organizer_headers):
        """PRD §3.4: "Capacity is aggregate, not pairwise: a slot's `booked_count` counts its bookings in `BOOKED` or `CHECKED_IN` status".

        Design: Difficulty/resource_temporal_overlap/slot_aggregate_capacity_not_pairwise
        """
        event = create_event()
        open_intake(event["id"])
        slot = create_slot(event["id"], capacity=2,
                           start_time="2026-06-02T10:00:00Z",
                           end_time="2026-06-02T12:00:00Z")
        c1 = register_consignor(event["id"], "Tal")
        c2 = register_consignor(event["id"], "Uli")

        b1 = book_slot(slot["id"], c1["id"])
        b2 = book_slot(slot["id"], c2["id"])
        assert b1["status"] == "BOOKED"
        assert b2["status"] == "BOOKED", (
            "Two bookings occupying the identical window must coexist under "
            "aggregate capacity semantics"
        )

    def test_aggregate_booked_count_tracks_both_bookings(self, api, organizer_headers):
        """PRD §3.4: "A successful booking starts in `BOOKED` and raises the slot's `booked_count` by one."

        Design: Difficulty/resource_temporal_overlap/slot_aggregate_capacity_not_pairwise
        """
        event = create_event()
        open_intake(event["id"])
        slot = create_slot(event["id"], capacity=2,
                           start_time="2026-06-02T10:00:00Z",
                           end_time="2026-06-02T12:00:00Z")
        c1 = register_consignor(event["id"], "Tal")
        c2 = register_consignor(event["id"], "Uli")
        book_slot(slot["id"], c1["id"])
        book_slot(slot["id"], c2["id"])

        slot_after = get_slot(slot["id"])
        assert slot_after["booked_count"] == 2, (
            f"Two successful bookings must raise booked_count to 2, got "
            f"{slot_after['booked_count']}"
        )


class TestDuplicateActiveBooking:

    def test_second_active_booking_rejected_until_first_cancelled(self, api, organizer_headers):
        """PRD §3.4: "Each consignor may hold at most one active booking per event — a second booking while one is already `BOOKED` or `CHECKED_IN` is rejected with `ERR_DUPLICATE_ACTIVE_BOOKING`."
        PRD §3.4: "Cancellation, available to the organizer or the owning consignor while the booking is still `BOOKED`, moves it to `CANCELLED` and decrements the slot's `booked_count` — a compensation that frees aggregate capacity."

        Design: Corner/errors/duplicate_active_booking_rejected
        """
        event = create_event()
        open_intake(event["id"])
        consignor = register_consignor(event["id"], "Ann")
        s1 = create_slot(event["id"], capacity=5,
                         start_time="2026-06-02T10:00:00Z", end_time="2026-06-02T12:00:00Z")
        s2 = create_slot(event["id"], capacity=5,
                         start_time="2026-06-02T14:00:00Z", end_time="2026-06-02T16:00:00Z")
        bk1 = book_slot(s1["id"], consignor["id"])

        resp = api.create_drop_off_booking(
            {"slot_id": s2["id"], "consignor_id": consignor["id"]},
            make_consignor_headers(consignor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_BOOKING)

        cancelled = validate_success(
            api.cancel_drop_off_booking(bk1["id"], make_consignor_headers(consignor["id"]))
        )
        assert cancelled["status"] == "CANCELLED"

        bk2 = book_slot(s2["id"], consignor["id"])
        assert bk2["status"] == "BOOKED", (
            "After cancelling the first booking, a new booking must succeed"
        )


class TestDropOffGating:

    def test_drop_off_without_checked_in_booking_rejected(self, api, organizer_headers):
        """PRD §3.4: "and the consignor must hold a booking in `CHECKED_IN` for the event, or the drop-off fails with `ERR_NO_CHECKED_IN_BOOKING`."

        Design: Difficulty/cross_entity_state_dependency/item_dropoff_requires_phase_and_checked_in_booking
        """
        event = create_event()
        open_intake(event["id"])
        consignor = register_consignor(event["id"], "Quy")
        slot = create_slot(event["id"])
        book_slot(slot["id"], consignor["id"])  # BOOKED, not checked in
        item = create_item_for(consignor["id"], price_cents=300, title="Books",
                               category="BOOKS")

        resp = api.drop_off_item(item["id"], make_consignor_headers(consignor["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_CHECKED_IN_BOOKING)
        assert get_item(item["id"])["status"] == "TAGGED", (
            "A rejected drop-off must leave the item TAGGED"
        )

    def test_drop_off_unlocked_by_booking_check_in(self, api, organizer_headers):
        """PRD §3.4: "At the venue, an organizer checks the booking in, moving `BOOKED` to `CHECKED_IN`".
        PRD §3.4: "A successful drop-off moves the item from `TAGGED` to `DROPPED_OFF` and triggers recomputation of the consignor's counters."

        Design: Difficulty/cross_entity_state_dependency/item_dropoff_requires_phase_and_checked_in_booking
        """
        event = create_event()
        open_intake(event["id"])
        consignor = register_consignor(event["id"], "Quy")
        slot = create_slot(event["id"])
        booking = book_slot(slot["id"], consignor["id"])
        item = create_item_for(consignor["id"], price_cents=300, title="Books",
                               category="BOOKS")

        check_in_booking(booking["id"])
        dropped = drop_off_item(item["id"], consignor["id"])
        assert dropped["status"] == "DROPPED_OFF", (
            "Once the booking transitions to CHECKED_IN, the drop-off must succeed"
        )

    def test_drop_off_twice_rejected(self, api, organizer_headers):
        """PRD §2.8: "fifth, the target entity's lifecycle state (the `ERR_*_WRONG_STATE` family, plus `ERR_TRANSACTION_NOT_OPEN`, `ERR_PASS_NOT_ACTIVE`, and `ERR_SETTLEMENTS_LOCKED`)".
        PRD §3.4: "A successful drop-off moves the item from `TAGGED` to `DROPPED_OFF` and triggers recomputation of the consignor's counters."

        Design: Corner/state_machines/item_drop_off_twice_rejected
        """
        event = create_event()
        open_intake(event["id"])
        consignor = register_consignor(event["id"], "Ann")
        slot = create_slot(event["id"])
        book_and_check_in(slot["id"], consignor["id"])
        item = create_item_for(consignor["id"], price_cents=500)
        drop_off_item(item["id"], consignor["id"])

        resp = api.drop_off_item(item["id"], make_consignor_headers(consignor["id"]))
        validate_error(resp, ApiErrorId.ERR_ITEM_WRONG_STATE)
        assert get_item(item["id"])["status"] == "DROPPED_OFF", (
            "A second drop-off must not change the item's state"
        )


class TestBookingReverseLookup:

    def test_list_bookings_filtered_by_consignor(self, api, organizer_headers):
        """PRD §3.4: "Bookings can be listed with `slot_id`, `consignor_id`, and `status` filters."

        Design: Corner/endpoints/fk_reverse_bookings_by_consignor
        """
        event = create_event()
        open_intake(event["id"])
        ann = register_consignor(event["id"], "Ann")
        bob = register_consignor(event["id"], "Bob")
        slot = create_slot(event["id"], capacity=5)
        booking = book_slot(slot["id"], ann["id"])

        ann_rows, ann_meta = validate_paginated(
            api.list_drop_off_bookings(organizer_headers,
                                       params={"consignor_id": ann["id"]})
        )
        assert ann_meta["total_count"] == 1
        assert [row["id"] for row in ann_rows] == [booking["id"]]

        bob_rows, bob_meta = validate_paginated(
            api.list_drop_off_bookings(organizer_headers,
                                       params={"consignor_id": bob["id"]})
        )
        assert bob_meta["total_count"] == 0
        assert bob_rows == []
