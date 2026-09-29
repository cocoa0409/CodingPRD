"""Cross-dock doors: aggregate pallet capacity over half-open overlap, the
sanitation separation buffer, window containment and appointment close-out."""

from test_helpers import (
    CLOCK_BASE,
    HUB,
    ApiErrorId,
    assert_dock_appointment,
    assert_dock_slot,
    book_appointment,
    close_appointment,
    create_dock_appointment_payload,
    create_dock_slot,
    dock_slot_version,
    make_producer_headers,
    onboard_active_producer,
    read_allocation,
    read_dock_appointment,
    read_dock_slot,
    read_order,
    read_product,
    set_clock,
    setup_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def _slot_with_first_appointment(pallets=6, risk_class="PRODUCE"):
    """One ACTIVE producer, one 12-pallet door with a 45-minute sanitation
    buffer, and one BOOKED appointment occupying [08:00, 09:00)."""
    set_clock(CLOCK_BASE)
    onboarded = onboard_active_producer()
    pid = onboarded["producer_id"]
    slot = create_dock_slot(pallet_capacity=12, sanitation_buffer_minutes=45)
    appointment = book_appointment(
        slot["id"],
        pid,
        pallets=pallets,
        risk_class=risk_class,
        arrival_start="2026-09-14T08:00:00Z",
        arrival_end="2026-09-14T09:00:00Z",
    )
    return pid, slot, appointment


class TestDockIntervalGeometry:
    def test_an_adjacent_appointment_does_not_overlap_and_books(self, api):
        """PRD 3.6: "The **capacity** test is an aggregate over overlap: the
        requested `pallets`, added to the pallets of every appointment on the
        same door that is `BOOKED` or `RECEIVED` and whose interval overlaps the
        requested one, must not exceed the door's `pallet_capacity`. Overlap
        here is half-open, so an appointment that ends exactly when the new one
        starts does not overlap it and contributes nothing."
        PRD 3.6: "A successful booking enters status `BOOKED` with
        `received_pallets` at 0 and no `recorded_temp_c`, the door's
        `pallets_booked` is recomputed as the summed pallets of its `BOOKED` and
        `RECEIVED` appointments, the door's derived status is refreshed, and the
        door's `version` is incremented by 1."

        Design: Difficulty/resource_temporal_overlap/dock_slot_aggregate_capacity_with_sanitation_buffer_geometry
        """
        pid, slot, _first = _slot_with_first_appointment()

        payload = create_dock_appointment_payload(
            slot["id"],
            pid,
            dock_slot_version(slot["id"]),
            arrival_start="2026-09-14T09:00:00Z",
            arrival_end="2026-09-14T10:00:00Z",
            pallets=5,
            risk_class="PRODUCE",
        )
        data = validate_success(
            api.create_dock_appointment(payload, make_producer_headers(pid)), 201
        )
        assert_dock_appointment(data)
        assert data["status"] == "BOOKED"
        assert data["received_pallets"] == 0
        assert data["recorded_temp_c"] is None

        slot_now = read_dock_slot(slot["id"])
        assert slot_now["pallets_booked"] == 11
        assert slot_now["status"] == "OPEN"
        assert_dock_slot(slot_now)

    def test_overlapping_pallets_beyond_the_door_capacity_are_refused(self, api):
        """PRD 3.6: "The **capacity** test is an aggregate over overlap: the
        requested `pallets`, added to the pallets of every appointment on the
        same door that is `BOOKED` or `RECEIVED` and whose interval overlaps the
        requested one, must not exceed the door's `pallet_capacity`. Overlap
        here is half-open, so an appointment that ends exactly when the new one
        starts does not overlap it and contributes nothing. Exceeding capacity
        is refused with `ERR_DOCK_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/dock_slot_aggregate_capacity_with_sanitation_buffer_geometry
        """
        pid, slot, _first = _slot_with_first_appointment()
        book_appointment(
            slot["id"],
            pid,
            pallets=5,
            risk_class="PRODUCE",
            arrival_start="2026-09-14T09:00:00Z",
            arrival_end="2026-09-14T10:00:00Z",
        )

        payload = create_dock_appointment_payload(
            slot["id"],
            pid,
            dock_slot_version(slot["id"]),
            arrival_start="2026-09-14T08:30:00Z",
            arrival_end="2026-09-14T09:30:00Z",
            pallets=5,
            risk_class="PRODUCE",
        )
        resp = api.create_dock_appointment(payload, make_producer_headers(pid))
        validate_error(resp, ApiErrorId.ERR_DOCK_CAPACITY_EXCEEDED.value, 409)

        slot_now = read_dock_slot(slot["id"])
        assert slot_now["pallets_booked"] == 11
        assert slot_now["status"] == "OPEN"
        _, meta = validate_paginated(
            api.list_dock_appointments(HUB, params={"dock_slot_id": slot["id"]})
        )
        assert meta["total_count"] == 2

    def test_a_differing_risk_class_inside_the_buffer_is_refused(self, api):
        """PRD 3.6: "The **sanitation** test is a separation requirement, and it
        is not restricted to overlapping neighbours: every appointment on the
        door that is `BOOKED` or `RECEIVED` and whose `risk_class` differs from
        the requested one must be separated from the requested interval by at
        least the door's `sanitation_buffer_minutes` on one side or the other —
        either the neighbour's end plus the buffer is at or before the new
        start, or the new end plus the buffer is at or before the neighbour's
        start. Anything closer is refused with
        `ERR_SANITATION_BUFFER_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/dock_slot_aggregate_capacity_with_sanitation_buffer_geometry
        """
        pid, slot, _first = _slot_with_first_appointment()
        book_appointment(
            slot["id"],
            pid,
            pallets=5,
            risk_class="PRODUCE",
            arrival_start="2026-09-14T09:00:00Z",
            arrival_end="2026-09-14T10:00:00Z",
        )

        payload = create_dock_appointment_payload(
            slot["id"],
            pid,
            dock_slot_version(slot["id"]),
            arrival_start="2026-09-14T09:15:00Z",
            arrival_end="2026-09-14T09:45:00Z",
            pallets=1,
            risk_class="RAW_ANIMAL",
        )
        resp = api.create_dock_appointment(payload, make_producer_headers(pid))
        validate_error(resp, ApiErrorId.ERR_SANITATION_BUFFER_VIOLATION.value, 409)

        slot_now = read_dock_slot(slot["id"])
        assert slot_now["pallets_booked"] == 11
        _, meta = validate_paginated(
            api.list_dock_appointments(HUB, params={"dock_slot_id": slot["id"]})
        )
        assert meta["total_count"] == 2

    def test_an_appointment_spilling_outside_the_door_window_is_refused(self, api):
        """PRD 3.6: "The requested interval must sit inside the door's own
        bookable window — at or after `window_start` and ending at or before
        `window_end` — and an interval spilling outside it, like one whose end
        is not strictly after its start, is refused with `ERR_INVALID_WINDOW`."

        Design: Corner/endpoints/dock_appointment_outside_the_slot_window_returns_invalid_window
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]
        slot = create_dock_slot(pallet_capacity=12, sanitation_buffer_minutes=45)

        payload = create_dock_appointment_payload(
            slot["id"],
            pid,
            slot["version"],
            arrival_start="2026-09-14T05:00:00Z",
            arrival_end="2026-09-14T06:30:00Z",
            pallets=2,
            risk_class="PRODUCE",
        )
        resp = api.create_dock_appointment(payload, make_producer_headers(pid))
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value, 422)

        assert read_dock_slot(slot["id"])["pallets_booked"] == 0
        _, meta = validate_paginated(
            api.list_dock_appointments(HUB, params={"dock_slot_id": slot["id"]})
        )
        assert meta["total_count"] == 0

    def test_booking_against_an_unknown_door_reports_dock_slot_not_found(self, api):
        """PRD 2.4: "Foreign keys supplied inside a request body are resolved
        the same way and with the same vocabulary: a catalog item created
        against an unknown `producer_id` fails with `ERR_PRODUCER_NOT_FOUND`; an
        order opened against an unknown `buyer_id` fails with
        `ERR_BUYER_NOT_FOUND`; an appointment naming an unknown `dock_slot_id`
        fails with `ERR_DOCK_SLOT_NOT_FOUND` and one naming an unknown
        `producer_id` with `ERR_PRODUCER_NOT_FOUND`; a route stop naming an
        unknown `order_id` fails with `ERR_ORDER_NOT_FOUND`; a rejection claim
        naming an unknown `allocation_id`, and a delivery record naming an
        allocation that is unknown or that belongs to a different order than the
        one in the path, both fail with `ERR_ALLOCATION_NOT_FOUND`."

        Design: Corner/errors/appointment_against_an_unknown_dock_slot_returns_not_found
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]
        slot = create_dock_slot(pallet_capacity=12, sanitation_buffer_minutes=45)

        payload = create_dock_appointment_payload(
            "00000000-0000-4000-8000-000000000000", pid, slot["version"]
        )
        resp = api.create_dock_appointment(payload, make_producer_headers(pid))
        validate_error(resp, ApiErrorId.ERR_DOCK_SLOT_NOT_FOUND.value, 404)
        assert read_dock_slot(slot["id"])["pallets_booked"] == 0

    def test_booking_against_a_stale_door_version_is_rejected(self, api):
        """PRD 2.7: "Booking a cross-dock appointment — the write at `POST
        /dock-appointments` — requires `expected_dock_slot_version`, carrying
        the `version` of the dock slot as the client last observed it. A
        mismatch with the slot's current `version` is rejected with
        `ERR_STALE_DOCK_SLOT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_dock_slot_version_on_a_second_appointment_is_rejected
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]
        slot = create_dock_slot(pallet_capacity=12, sanitation_buffer_minutes=45)
        stale_version = slot["version"]
        book_appointment(
            slot["id"],
            pid,
            pallets=2,
            arrival_start="2026-09-14T08:00:00Z",
            arrival_end="2026-09-14T09:00:00Z",
        )

        payload = create_dock_appointment_payload(
            slot["id"],
            pid,
            stale_version,
            arrival_start="2026-09-14T10:00:00Z",
            arrival_end="2026-09-14T11:00:00Z",
            pallets=2,
            risk_class="PRODUCE",
        )
        resp = api.create_dock_appointment(payload, make_producer_headers(pid))
        validate_error(resp, ApiErrorId.ERR_STALE_DOCK_SLOT_VERSION.value, 412)

        assert read_dock_slot(slot["id"])["pallets_booked"] == 2
        _, meta = validate_paginated(
            api.list_dock_appointments(HUB, params={"dock_slot_id": slot["id"]})
        )
        assert meta["total_count"] == 1

    def test_the_appointment_list_combines_a_filter_with_limit_and_offset(self, api):
        """PRD 2.3: "The `meta` block of a list response carries `limit`,
        `offset`, `total_count` and `has_more`: `total_count` is the number of
        records matching the filters before pagination is applied, and
        `has_more` is true when the offset plus the number of returned records
        is less than `total_count`."
        PRD 2.3: "The dock appointment list filters on `dock_slot_id`,
        `producer_id` and `status`."

        Design: Corner/cross_cutting_complexity_layers/dock_appointment_list_combines_filter_limit_and_offset
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]
        slot = create_dock_slot(pallet_capacity=12, sanitation_buffer_minutes=45)
        first = book_appointment(
            slot["id"], pid, pallets=2,
            arrival_start="2026-09-14T08:00:00Z",
            arrival_end="2026-09-14T09:00:00Z",
        )
        book_appointment(
            slot["id"], pid, pallets=2,
            arrival_start="2026-09-14T09:00:00Z",
            arrival_end="2026-09-14T10:00:00Z",
        )
        book_appointment(
            slot["id"], pid, pallets=2,
            arrival_start="2026-09-14T10:00:00Z",
            arrival_end="2026-09-14T11:00:00Z",
        )

        page_one, meta_one = validate_paginated(
            api.list_dock_appointments(
                HUB,
                params={
                    "dock_slot_id": slot["id"],
                    "status": "BOOKED",
                    "limit": 2,
                    "offset": 0,
                },
            )
        )
        assert len(page_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert page_one[0]["id"] == first["id"]

        page_two, meta_two = validate_paginated(
            api.list_dock_appointments(
                HUB,
                params={
                    "dock_slot_id": slot["id"],
                    "status": "BOOKED",
                    "limit": 2,
                    "offset": 2,
                },
            )
        )
        assert len(page_two) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False
        assert read_dock_slot(slot["id"])["pallets_booked"] == 6


class TestAppointmentCloseOut:
    def test_a_second_close_out_on_a_received_appointment_is_refused(self, api):
        """PRD 3.6: "Closing out an appointment is a hub administrator's act and
        takes an `outcome` of `RECEIVED`, `NO_SHOW` or `CANCELLED`; an
        appointment not currently `BOOKED` cannot be closed out and the attempt
        is refused with `ERR_INVALID_APPOINTMENT_STATE`."

        Design: Corner/errors/second_receipt_on_a_closed_appointment_returns_invalid_appointment_state
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]
        slot = create_dock_slot(pallet_capacity=12, sanitation_buffer_minutes=45)
        appointment = book_appointment(slot["id"], pid, pallets=2)
        close_appointment(
            appointment["id"], "RECEIVED", received_pallets=2, recorded_temp_c=1.5
        )

        resp = api.close_appointment(appointment["id"], {"outcome": "NO_SHOW"}, HUB)
        validate_error(resp, ApiErrorId.ERR_INVALID_APPOINTMENT_STATE.value, 409)

        assert read_dock_appointment(appointment["id"])["status"] == "RECEIVED"
        assert read_dock_slot(slot["id"])["pallets_booked"] == 2

    def test_a_cancelled_appointment_frees_pallets_without_touching_allocations(
        self, api
    ):
        """PRD 3.6: "A `BOOKED → CANCELLED` outcome is the gentle case: the
        door's `pallets_booked` is recomputed without the appointment and its
        status refreshed, and no allocation anywhere is touched."

        Design: Corner/state_machines/cancelled_dock_appointment_frees_pallets_without_reversing_allocations
        """
        scenario = setup_scenario(stage="aggregated")
        slot = create_dock_slot(pallet_capacity=12, sanitation_buffer_minutes=45)
        appointment = book_appointment(slot["id"], scenario["producer_id"], pallets=2)

        data = validate_success(
            api.close_appointment(appointment["id"], {"outcome": "CANCELLED"}, HUB)
        )
        assert data["status"] == "CANCELLED"

        slot_now = read_dock_slot(slot["id"])
        assert slot_now["pallets_booked"] == 0
        assert slot_now["status"] == "OPEN"
        assert read_allocation(scenario["allocation_id"])["status"] == "RESERVED"
        assert read_product(scenario["product_id"])["quantity_committed"] == 60
        order_now = read_order(scenario["order_id"])
        assert order_now["fulfillment_status"] == "AGGREGATED"
        assert order_now["order_total_cents"] == 124200
