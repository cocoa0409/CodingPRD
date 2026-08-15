"""Distribution day: venue overlap geometry, pickup-slot capacity, slot
containment, cross-campaign references, appointment lifecycle cascades, and
the complete-distribution gate."""
from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    TEST_USERS,
    close_ordering_at_window_end,
    create_and_submit_order,
    create_distribution_event_payload,
    create_pickup_appointment_payload,
    create_submitted_paid_order,
    drive_campaign_to_delivered,
    drive_campaign_to_distribution_complete,
    drive_campaign_to_sorted,
    generate_and_verify_tickets,
    get_success_data,
    reset_clock,
    setup_open_campaign_with_seller,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
TREAS = TEST_USERS["treasurer_headers"]


class TestVenueOverlapGeometry:
    def test_venue_half_open_adjacency_allowed_overlap_rejected(self, api):
        """PRD §3.5: "Two `SCHEDULED` events for the same campaign and venue
        may not have overlapping half-open windows; an overlapping creation is
        rejected with `ERR_VENUE_OVERLAP`."
        PRD §3.5: "a half-open occupancy window from `window_start`
        (inclusive) to `window_end` (exclusive, and strictly later than the
        start)".

        Design: Difficulty/resource_temporal_overlap/venue_half_open_adjacency_allowed_overlap_rejected
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        supplier_order = get_success_data(
            api.create_supplier_order({"campaign_id": campaign["id"]}, ADMIN))
        get_success_data(api.submit_supplier_order(supplier_order["id"], ADMIN))
        from test_helpers import acknowledge_supplier_order
        acknowledge_supplier_order(supplier_order["id"], product["id"], 600)

        first = validate_success(api.create_distribution_event(
            create_distribution_event_payload(campaign_id=campaign["id"]),
            COORD), 201)
        # Back-to-back: start == prior end is adjacency, legal under [start, end).
        second = validate_success(api.create_distribution_event(
            create_distribution_event_payload(
                campaign_id=campaign["id"],
                window_start="2026-09-06T18:00:00Z",
                window_end="2026-09-06T21:00:00Z", slot_capacity=1),
            COORD), 201)
        assert second["id"] != first["id"]
        # A one-minute intrusion into [15:00, 18:00) overlaps.
        intrusion = api.create_distribution_event(
            create_distribution_event_payload(
                campaign_id=campaign["id"],
                window_start="2026-09-06T17:59:00Z",
                window_end="2026-09-06T20:00:00Z", slot_capacity=1),
            COORD)
        validate_error(intrusion, ApiErrorId.ERR_VENUE_OVERLAP)

    def test_venue_overlap_scoped_to_campaign_and_venue(self, api):
        """PRD §3.5: "Two `SCHEDULED` events for the same campaign and venue
        may not have overlapping half-open windows".

        Design: Difficulty/resource_temporal_overlap/venue_half_open_adjacency_allowed_overlap_rejected
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        create_and_submit_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        supplier_order = get_success_data(
            api.create_supplier_order({"campaign_id": campaign["id"]}, ADMIN))
        get_success_data(api.submit_supplier_order(supplier_order["id"], ADMIN))
        from test_helpers import acknowledge_supplier_order
        acknowledge_supplier_order(supplier_order["id"], product["id"], 600)

        validate_success(api.create_distribution_event(
            create_distribution_event_payload(campaign_id=campaign["id"]),
            COORD), 201)
        # A different venue overlaps freely: the rule is scoped to
        # (campaign, venue).
        other_venue = api.create_distribution_event(
            create_distribution_event_payload(
                campaign_id=campaign["id"], venue="Pool",
                window_start="2026-09-06T17:00:00Z",
                window_end="2026-09-06T19:00:00Z", slot_capacity=1),
            COORD)
        validate_success(other_venue, 201)


class TestPickupSlotCapacity:
    def test_slot_capacity_aggregate_overlap_counting(self, api):
        """PRD §3.5: "Capacity is enforced at every instant: if the new
        booking would push the number of concurrently overlapping `BOOKED`
        appointments above the event's `slot_capacity` at any instant, the
        booking is rejected with `ERR_SLOT_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/slot_capacity_aggregate_overlap_counting
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        orders = [
            create_and_submit_order(seller["id"], product["id"], 1,
                                    family_contact_name=f"Fam{i}")
            for i in (1, 2, 3)
        ]
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_delivered(campaign["id"], product["id"], 12)
        generate_and_verify_tickets(campaign["id"])
        get_success_data(api.mark_sorted(campaign["id"], COORD))
        # Events are schedulable once the campaign is SUPPLIER_ORDERED or
        # beyond (PRD §3.5); SORTED satisfies that gate.
        event = get_success_data(api.create_distribution_event(
            create_distribution_event_payload(
                campaign_id=campaign["id"],
                window_start="2026-09-06T15:00:00Z",
                window_end="2026-09-06T16:00:00Z", slot_capacity=2),
            COORD))

        a1 = validate_success(api.create_pickup_appointment(
            create_pickup_appointment_payload(
                distribution_event_id=event["id"], order_id=orders[0]["id"],
                slot_start="2026-09-06T15:00:00Z",
                slot_end="2026-09-06T15:20:00Z"),
            COORD), 201)
        a2 = validate_success(api.create_pickup_appointment(
            create_pickup_appointment_payload(
                distribution_event_id=event["id"], order_id=orders[1]["id"],
                slot_start="2026-09-06T15:10:00Z",
                slot_end="2026-09-06T15:30:00Z"),
            COORD), 201)
        assert a1["status"] == "BOOKED" and a2["status"] == "BOOKED", (
            "two overlapping slots at capacity 2 are allowed")

        over = api.create_pickup_appointment(
            create_pickup_appointment_payload(
                distribution_event_id=event["id"], order_id=orders[2]["id"],
                slot_start="2026-09-06T15:15:00Z",
                slot_end="2026-09-06T15:35:00Z"),
            COORD)
        validate_error(over, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED)

        # 15:30 is the exclusive end of a2: concurrency drops back below 2.
        a3 = validate_success(api.create_pickup_appointment(
            create_pickup_appointment_payload(
                distribution_event_id=event["id"], order_id=orders[2]["id"],
                slot_start="2026-09-06T15:30:00Z",
                slot_end="2026-09-06T15:45:00Z"),
            COORD), 201)
        assert a3["status"] == "BOOKED"
        data, meta = validate_paginated(api.list_pickup_appointments(
            COORD, params={"distribution_event_id": event["id"]}))
        assert len(data) == 3 and meta["total_count"] == 3

    def test_slot_capacity_boundary_counts_only_booked(self, api):
        """PRD §3.5: "if the new booking would push the number of concurrently
        overlapping `BOOKED` appointments above the event's `slot_capacity` at
        any instant, the booking is rejected with
        `ERR_SLOT_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/slot_capacity_aggregate_overlap_counting
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        orders = [
            create_and_submit_order(seller["id"], product["id"], 1,
                                    family_contact_name=f"Fam{i}")
            for i in (1, 2, 3)
        ]
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_delivered(campaign["id"], product["id"], 12)
        generate_and_verify_tickets(campaign["id"])
        get_success_data(api.mark_sorted(campaign["id"], COORD))
        # Events are schedulable once the campaign is SUPPLIER_ORDERED or
        # beyond (PRD §3.5); SORTED satisfies that gate.
        event = get_success_data(api.create_distribution_event(
            create_distribution_event_payload(
                campaign_id=campaign["id"],
                window_start="2026-09-06T15:00:00Z",
                window_end="2026-09-06T16:00:00Z", slot_capacity=1),
            COORD))

        a1 = validate_success(api.create_pickup_appointment(
            create_pickup_appointment_payload(
                distribution_event_id=event["id"], order_id=orders[0]["id"],
                slot_start="2026-09-06T15:00:00Z",
                slot_end="2026-09-06T15:30:00Z"),
            COORD), 201)
        # Cancel a1: its slot no longer counts as BOOKED.
        get_success_data(api.cancel_pickup_appointment(a1["id"], COORD))
        a2 = validate_success(api.create_pickup_appointment(
            create_pickup_appointment_payload(
                distribution_event_id=event["id"], order_id=orders[1]["id"],
                slot_start="2026-09-06T15:05:00Z",
                slot_end="2026-09-06T15:25:00Z"),
            COORD), 201)
        assert a2["status"] == "BOOKED", (
            "a CANCELLED booking frees its concurrency share")
        blocked = api.create_pickup_appointment(
            create_pickup_appointment_payload(
                distribution_event_id=event["id"], order_id=orders[2]["id"],
                slot_start="2026-09-06T15:10:00Z",
                slot_end="2026-09-06T15:20:00Z"),
            COORD)
        validate_error(blocked, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED)


class TestAppointmentContainment:
    def test_appointment_outside_event_window_rejected(self, api):
        """PRD §3.5: "The slot must be contained within the event's window —
        `slot_start` at or after `window_start`, and `slot_end` strictly after
        `slot_start` and at or before `window_end` — else
        `ERR_APPOINTMENT_WINDOW_OUTSIDE`."

        Design: Corner/validations/appointment_outside_event_window_rejected
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_and_submit_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_delivered(campaign["id"], product["id"], 12)
        generate_and_verify_tickets(campaign["id"])
        get_success_data(api.mark_sorted(campaign["id"], COORD))
        # Events are schedulable once the campaign is SUPPLIER_ORDERED or
        # beyond (PRD §3.5); SORTED satisfies that gate.
        event = get_success_data(api.create_distribution_event(
            create_distribution_event_payload(campaign_id=campaign["id"]),
            COORD))

        overrun = api.create_pickup_appointment(
            create_pickup_appointment_payload(
                distribution_event_id=event["id"], order_id=order["id"],
                slot_start="2026-09-06T17:45:00Z",
                slot_end="2026-09-06T18:05:00Z"),
            COORD)
        validate_error(overrun, ApiErrorId.ERR_APPOINTMENT_WINDOW_OUTSIDE)

        full_window = api.create_pickup_appointment(
            create_pickup_appointment_payload(
                distribution_event_id=event["id"], order_id=order["id"],
                slot_start="2026-09-06T15:00:00Z",
                slot_end="2026-09-06T18:00:00Z"),
            COORD)
        booked = validate_success(full_window, 201)
        assert booked["status"] == "BOOKED", (
            "a slot spanning the full window exactly is contained")

    def test_cross_campaign_appointment_rejected(self, api):
        """PRD §3.5: "the event and the order must belong to the same campaign
        (else `ERR_CROSS_CAMPAIGN_REFERENCE`)".

        Design: Corner/validations/cross_campaign_appointment_rejected
        """
        from test_helpers import (
            create_campaign, create_group, create_product, create_seller)
        reset_clock()
        # Campaign A reaches SUPPLIER_ORDERED with a SCHEDULED event.
        camp_a = create_campaign(name="Sale A")
        group_a = create_group(camp_a["id"], name="Group A")
        product_a = create_product(camp_a["id"])
        seller_a = create_seller(group_a["id"], display_name="Alice")
        get_success_data(api.open_campaign(camp_a["id"], ADMIN))
        order_a = create_and_submit_order(seller_a["id"], product_a["id"], 1)
        close_ordering_at_window_end(camp_a["id"])
        so_a = get_success_data(
            api.create_supplier_order({"campaign_id": camp_a["id"]}, ADMIN))
        get_success_data(api.submit_supplier_order(so_a["id"], ADMIN))
        from test_helpers import acknowledge_supplier_order
        acknowledge_supplier_order(so_a["id"], product_a["id"], 600)
        event_a = get_success_data(api.create_distribution_event(
            create_distribution_event_payload(campaign_id=camp_a["id"]), COORD))

        # Campaign B reaches SORTED with a SORTED order. Rewind the clock into
        # the order window first: opening is rejected once the clock has
        # reached order_window_end (PRD §3.1).
        reset_clock()
        camp_b = create_campaign(name="Sale B")
        group_b = create_group(camp_b["id"], name="Group B")
        product_b = create_product(camp_b["id"])
        seller_b = create_seller(group_b["id"], display_name="Bobby")
        get_success_data(api.open_campaign(camp_b["id"], ADMIN))
        order_b = create_and_submit_order(seller_b["id"], product_b["id"], 1)
        close_ordering_at_window_end(camp_b["id"])
        drive_campaign_to_sorted(camp_b["id"], product_b["id"], 12)

        resp = api.create_pickup_appointment(
            create_pickup_appointment_payload(
                distribution_event_id=event_a["id"], order_id=order_b["id"]),
            COORD)
        validate_error(resp, ApiErrorId.ERR_CROSS_CAMPAIGN_REFERENCE)
        assert order_a["id"] != order_b["id"]

    def test_appointment_booking_requires_order_sorted(self, api):
        """PRD §3.5: "The event must be `SCHEDULED` and the order's
        fulfillment must be `SORTED` (else `ERR_INVALID_STATE`)".

        Design: Difficulty/cross_entity_state_dependency/appointment_booking_requires_order_sorted
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_and_submit_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_delivered(campaign["id"], product["id"], 12)
        event = get_success_data(api.create_distribution_event(
            create_distribution_event_payload(campaign_id=campaign["id"]),
            COORD))
        get_success_data(api.generate_sort_tickets(campaign["id"], COORD))
        tickets, _meta = validate_paginated(
            api.list_sort_tickets(COORD, params={"campaign_id": campaign["id"]}))
        get_success_data(api.verify_sort_ticket(
            tickets[0]["id"], {"verified_qty": 1}, COORD))
        # mark-sorted NOT yet called: the order's fulfillment is still PENDING.
        blocked = api.create_pickup_appointment(
            create_pickup_appointment_payload(
                distribution_event_id=event["id"], order_id=order["id"]),
            COORD)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)

        get_success_data(api.mark_sorted(campaign["id"], COORD))
        booked = validate_success(api.create_pickup_appointment(
            create_pickup_appointment_payload(
                distribution_event_id=event["id"], order_id=order["id"]),
            COORD), 201)
        assert booked["status"] == "BOOKED"
        assert booked["distribution_event_id"] == event["id"]

    def test_appointment_gate_follows_fulfillment_dimension(self, api):
        """PRD §3.4: "The cascade moves every non-cancelled order whose
        `fulfillment_status` is still `PENDING` to `SORTED`".

        Design: Difficulty/cross_entity_state_dependency/appointment_booking_requires_order_sorted
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_and_submit_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_sorted(campaign["id"], product["id"], 12)
        view = get_success_data(api.get_order(order["id"], COORD))
        assert view["fulfillment_status"] == "SORTED", (
            "mark-sorted moves the order's fulfillment dimension to SORTED")


class TestEventCancellationCascade:
    def test_event_cancel_cascades_appointments(self, api):
        """PRD §3.5: "may instead be cancelled (`SCHEDULED` → `CANCELLED`),
        which cascades its `BOOKED` appointments to `CANCELLED`."
        PRD §2.10: "Seventh, state-machine admission: the target entity — or,
        for creates, the related entity whose lifecycle gates creation — must
        be in a permitting state, else `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/event_cancel_cascades_appointments
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        order = create_and_submit_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_sorted(campaign["id"], product["id"], 12)
        # Events are schedulable once the campaign is SUPPLIER_ORDERED or
        # beyond (PRD §3.5); SORTED satisfies that gate.
        event = get_success_data(api.create_distribution_event(
            create_distribution_event_payload(campaign_id=campaign["id"]),
            COORD))
        appointment = get_success_data(api.create_pickup_appointment(
            create_pickup_appointment_payload(
                distribution_event_id=event["id"], order_id=order["id"]),
            COORD))
        assert appointment["status"] == "BOOKED"

        get_success_data(api.cancel_distribution_event(event["id"], COORD))
        after = get_success_data(
            api.get_pickup_appointment(appointment["id"], COORD))
        assert after["status"] == "CANCELLED", (
            "the event cascade cancels its BOOKED appointments")
        complete = api.complete_pickup_appointment(
            appointment["id"], {"outcome": "COMPLETED"}, COORD)
        validate_error(complete, ApiErrorId.ERR_INVALID_STATE)
