"""Campus events, seat invariant, fee waivers, and event window overlap
(PRD §3.2, §3.9)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    register_owner,
    owner_headers,
    create_active_partner_org,
    create_event_payload,
    create_bicycle_payload,
    setup_published_event,
    book_seat,
    get_success_data,
    api_client,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


class TestBookingAndWaivers:
    def test_event_registration_defaults_and_waiver_minting(self, api):
        """PRD §3.9: "A successful booking creates the registration in `BOOKED`
        status with the acting owner recorded as `owner_id` and the event as
        `event_id`, mints a fee-waiver `waiver_code` for the booking with
        `waiver_used` initially false,"

        Design: Corner/entities/event_registration_defaults_and_waiver_minting
        """
        _org, event = setup_published_event(capacity=5)
        owner = register_owner("o1@x.com", "O One")
        registration = book_seat(event, owner)
        assert registration["status"] == "BOOKED"
        assert registration["owner_id"] == owner["id"]
        assert registration["event_id"] == event["id"]
        assert isinstance(registration["waiver_code"], str) and registration["waiver_code"], (
            "booking must mint a non-empty server-side waiver_code"
        )
        assert registration["waiver_used"] is False, (
            f"waiver_used must start false, got {registration['waiver_used']}"
        )

    def test_waiver_code_single_use_enforced(self, api):
        """PRD §3.2: "A waiver code is valid only when it resolves to an issued
        code that has not been used before, whose issuing event is not `CANCELLED`,
        and where the current logical time is no later than thirty days after that
        event's `ends_at`; any other code is rejected with
        `ERR_WAIVER_CODE_INVALID` (HTTP 422). Consumption flips the issuing event
        registration's `waiver_used` flag to true."
        PRD §3.2: "When a valid `waiver_code` is supplied, the fee becomes zero
        after the per-component computation — the waiver applies a full discount."

        Design: Corner/validations/waiver_code_single_use_enforced
        """
        _org, event = setup_published_event(capacity=5)
        owner = register_owner("o1@x.com", "O One")
        registration = book_seat(event, owner)
        waiver = registration["waiver_code"]
        first = validate_success(
            api.create_bicycle(
                create_bicycle_payload(
                    serial_number="WVR001", declared_value_cents=100000,
                    photo_url="https://x/1.jpg", waiver_code=waiver,
                ),
                owner_headers(owner),
            ),
            expected_status=201,
        )
        assert first["registration_fee_cents"] == 0, (
            f"a valid waiver zeroes the fee, got {first['registration_fee_cents']}"
        )
        assert first["waiver_code_used"] == waiver
        second = api.create_bicycle(
            create_bicycle_payload(
                serial_number="WVR002", declared_value_cents=100000,
                photo_url="https://x/2.jpg", waiver_code=waiver,
            ),
            owner_headers(owner),
        )
        validate_error(second, ApiErrorId.ERR_WAIVER_CODE_INVALID, expected_status=422)
        registration_after = validate_success(
            api.get_event_registration(registration["id"], REGISTRAR)
        )
        assert registration_after["waiver_used"] is True, (
            "consumption must flip the issuing registration's waiver_used flag"
        )


class TestEventCreation:
    def test_event_host_not_campus_rejected(self, api):
        """PRD §3.9: "The host must be a partner organization of `org_type`
        `CAMPUS` (otherwise `ERR_EVENT_HOST_NOT_CAMPUS`, HTTP 422) and must be
        `ACTIVE` at creation time (otherwise `ERR_PARTNER_ORG_NOT_ACTIVE`)."

        Design: Corner/validations/event_host_not_campus_rejected
        """
        org = create_active_partner_org()  # LAW_ENFORCEMENT, ACTIVE
        resp = api.create_event(create_event_payload(org["id"]), ADMIN)
        validate_error(resp, ApiErrorId.ERR_EVENT_HOST_NOT_CAMPUS, expected_status=422)


class TestEventWindowOverlap:
    def test_event_window_half_open_adjacency(self, api):
        """PRD §3.9: "Windows are half-open — an event occupies from its
        `starts_at` inclusive up to its `ends_at` exclusive — and two windows
        overlap only when the new event's start falls before the existing event's
        end and the existing event's start falls before the new event's end;
        windows that merely touch at an endpoint do not overlap. A violation fails
        with `ERR_EVENT_WINDOW_OVERLAP`."

        e1 occupies [09:00, 12:00); e2 [12:00, 15:00) merely touches it and
        publishes; e3 [11:00, 14:00) genuinely overlaps and is rejected.

        Design: Difficulty/resource_temporal_overlap/event_window_half_open_adjacency
        """
        set_clock("2026-05-01T00:00:00Z")
        org = create_active_partner_org(
            name="State Univ", org_type="CAMPUS",
            jurisdiction_code="SU-1", contact_email="su@x.edu",
        )
        event1 = get_success_data(
            api_client.create_event(
                create_event_payload(
                    org["id"], title="E1",
                    starts_at="2026-06-01T09:00:00Z", ends_at="2026-06-01T12:00:00Z",
                    capacity=10,
                ),
                ADMIN,
            )
        )
        get_success_data(api_client.publish_event(event1["id"], ADMIN))
        # Adjacent at the endpoint: allowed by half-open semantics.
        event2 = get_success_data(
            api_client.create_event(
                create_event_payload(
                    org["id"], title="E2",
                    starts_at="2026-06-01T12:00:00Z", ends_at="2026-06-01T15:00:00Z",
                    capacity=10,
                ),
                ADMIN,
            )
        )
        published2 = validate_success(api.publish_event(event2["id"], ADMIN))
        assert published2["status"] == "PUBLISHED", (
            "an event starting exactly at the existing event's ends_at is adjacent, "
            "not overlapping"
        )
        # One hour of genuine overlap with both published windows.
        event3 = get_success_data(
            api_client.create_event(
                create_event_payload(
                    org["id"], title="E3", venue="Hall",
                    starts_at="2026-06-01T11:00:00Z", ends_at="2026-06-01T14:00:00Z",
                    capacity=10,
                ),
                ADMIN,
            )
        )
        resp = api.publish_event(event3["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_OVERLAP, expected_status=409)

    def test_event_window_overlap_scoped_per_host(self, api):
        """PRD §3.9: "no other `PUBLISHED` event of the same host organization may
        have an overlapping window."

        An identical window under a different host organization publishes fine.

        Design: Difficulty/resource_temporal_overlap/event_window_half_open_adjacency
        """
        set_clock("2026-05-01T00:00:00Z")
        org_a = create_active_partner_org(
            name="State Univ", org_type="CAMPUS",
            jurisdiction_code="SU-1", contact_email="su@x.edu",
        )
        org_b = create_active_partner_org(
            name="City College", org_type="CAMPUS",
            jurisdiction_code="CC-1", contact_email="cc@x.edu",
        )
        event_a = get_success_data(
            api_client.create_event(create_event_payload(org_a["id"], capacity=10), ADMIN)
        )
        get_success_data(api_client.publish_event(event_a["id"], ADMIN))
        event_b = get_success_data(
            api_client.create_event(
                create_event_payload(org_b["id"], title="Other host", capacity=10), ADMIN
            )
        )
        published_b = validate_success(api.publish_event(event_b["id"], ADMIN))
        assert published_b["status"] == "PUBLISHED", (
            "the overlap rule is per host organization; other hosts are unaffected"
        )


class TestSeatInvariant:
    def test_event_register_then_cancel_seat_conservation(self, api):
        """PRD §3.9: "The seat invariant is exact and continuous:
        `registered_count` always equals the number of the event's registrations
        currently in `BOOKED` status and always stays within zero and `capacity`
        inclusive. Cancelling a booking — the compensating action, available to the
        registration's own owner while it is `BOOKED` — moves it to `CANCELLED`,
        decrements `registered_count` by 1, and increments the event's `version`;"

        Design: Difficulty/compensating_invariant/event_register_then_cancel_seat_conservation
        """
        _org, event = setup_published_event(capacity=2)
        owner = register_owner("o1@x.com", "O One")
        registration = book_seat(event, owner)
        assert registration["status"] == "BOOKED"
        after_book = validate_success(api.get_event(event["id"], REGISTRAR))
        assert after_book["registered_count"] == 1, (
            f"booking must increment registered_count to 1, got {after_book['registered_count']}"
        )
        cancelled = validate_success(
            api.cancel_event_registration(registration["id"], owner_headers(owner))
        )
        assert cancelled["status"] == "CANCELLED"
        after_cancel = validate_success(api.get_event(event["id"], REGISTRAR))
        assert after_cancel["registered_count"] == 0, (
            "the compensating cancel must restore registered_count to 0"
        )
        assert after_cancel["capacity"] == 2, "capacity is unchanged by book/cancel"
        booked, meta = validate_paginated(
            api.list_event_registrations(
                REGISTRAR, params={"event_id": event["id"], "status": "BOOKED"}
            )
        )
        assert meta["total_count"] == 0 and booked == [], (
            "registered_count must equal COUNT(BOOKED registrations) == 0"
        )

    def test_event_cancel_cascade_drives_count_to_zero(self, api):
        """PRD §3.9: "cancelling a `PUBLISHED` event cascades — every `BOOKED`
        registration moves to `CANCELLED`, the `registered_count` is recomputed to
        zero, the event's `version` increments."
        PRD §3.9: "the event-cancellation cascade above is the bulk form of the
        same invariant, driving the count to zero."

        Design: Difficulty/compensating_invariant/event_register_then_cancel_seat_conservation
        """
        _org, event = setup_published_event(capacity=5)
        owner1 = register_owner("o1@x.com", "O One")
        owner2 = register_owner("o2@x.com", "O Two")
        reg1 = book_seat(event, owner1)
        reg2 = book_seat(event, owner2)
        after_books = validate_success(api.get_event(event["id"], REGISTRAR))
        assert after_books["registered_count"] == 2
        cancelled_event = validate_success(api.cancel_event(event["id"], ADMIN))
        assert cancelled_event["status"] == "CANCELLED"
        assert cancelled_event["registered_count"] == 0, (
            f"the cascade must recompute registered_count to 0, got "
            f"{cancelled_event['registered_count']}"
        )
        for reg in (reg1, reg2):
            read_back = validate_success(api.get_event_registration(reg["id"], REGISTRAR))
            assert read_back["status"] == "CANCELLED", (
                f"BOOKED registrations must cascade to CANCELLED, got {read_back['status']}"
            )


class TestBookingGuards:
    def test_event_capacity_full_rejected(self, api):
        """PRD §3.9: "the event's `registered_count` must still be below its
        `capacity` (a full event rejects with `ERR_EVENT_CAPACITY_FULL`, HTTP
        422),"

        Design: Corner/errors/event_capacity_full_rejected
        """
        _org, event = setup_published_event(capacity=1)
        owner1 = register_owner("o1@x.com", "O One")
        owner2 = register_owner("o2@x.com", "O Two")
        book_seat(event, owner1)  # the capacity-th seat succeeds
        resp = api.book_event_seat(event["id"], owner_headers(owner2))
        validate_error(resp, ApiErrorId.ERR_EVENT_CAPACITY_FULL, expected_status=422)
        after = validate_success(api.get_event(event["id"], REGISTRAR))
        assert after["registered_count"] == 1 == after["capacity"]

    def test_duplicate_booking_same_event_rejected(self, api):
        """PRD §3.9: "an owner may hold at most one `BOOKED` registration per
        event (a repeat booking rejects with `ERR_EVENT_REGISTRATION_EXISTS`)."

        Design: Corner/errors/duplicate_booking_same_event_rejected
        """
        _org, event = setup_published_event(capacity=5)
        owner = register_owner("o1@x.com", "O One")
        book_seat(event, owner)
        resp = api.book_event_seat(event["id"], owner_headers(owner))
        validate_error(resp, ApiErrorId.ERR_EVENT_REGISTRATION_EXISTS, expected_status=409)

    def test_registration_after_event_end_rejected(self, api):
        """PRD §3.9: "An owner books a seat at a `PUBLISHED` event (any other state
        fails with `ERR_EVENT_NOT_PUBLISHED`) while the current logical time is
        still before the event's `ends_at` (otherwise `ERR_EVENT_ENDED`)."

        Booking exactly at ends_at fails: the bound is exclusive.

        Design: Corner/errors/registration_after_event_end_rejected
        """
        _org, event = setup_published_event(capacity=5)
        owner = register_owner("o1@x.com", "O One")
        set_clock("2026-06-01T12:00:00Z")  # exactly at ends_at
        resp = api.book_event_seat(event["id"], owner_headers(owner))
        validate_error(resp, ApiErrorId.ERR_EVENT_ENDED, expected_status=409)
