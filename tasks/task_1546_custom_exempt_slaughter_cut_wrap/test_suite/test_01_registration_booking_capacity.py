"""Registration, booking, capacity-day rules, and the reschedule self-loop.

Covers customer/capacity-day creation rules, booking well-formedness and auth,
the 14-day lead-time boundary, whole-day capacity aggregation, the
book/cancel capacity invariant, and the OCC-guarded reschedule self-loop.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_appointment,
    assert_capacity_day,
    assert_customer,
    book_appointment,
    book_and_confirm,
    create_appointment_payload,
    create_capacity_day,
    create_capacity_day_payload,
    create_customer,
    get_appointment,
    get_capacity_day_by_date,
    get_customer,
    get_success_data,
    make_customer_headers,
    reschedule_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

OP = TEST_USERS["operator_headers"]
MGR = TEST_USERS["manager_headers"]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestRegistrationAndReads:
    def test_customer_creation_applies_defaults(self, api):
        """PRD §3.1: "A new customer starts with `no_show_strikes` at zero and
        standing `ACTIVE`."
        PRD §2.5: "`id` — a server-minted UUID string with no type prefix."
        PRD §2.4: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and until it is explicitly set it never
        consults the wall clock."

        Design: Corner/entities/customer_creation_applies_defaults
        """
        resp = api.create_customer(
            {"name": "Ann Orr", "phone": "555-0101", "email": "ann@x.com"}, OP
        )
        data = validate_success(resp, expected_status=201)
        assert_customer(data)
        assert data["status"] == "ACTIVE"
        assert data["no_show_strikes"] == 0
        # created_at is system-stamped against the logical clock, which reads
        # exactly 2026-08-01T00:00:00Z at startup (PRD §2.4).
        assert _parse(data["created_at"]) == _parse("2026-08-01T00:00:00Z")

    def test_customer_get_missing_returns_not_found(self, api):
        """PRD §2.8: "every `id` appearing in a request path is validated for
        existence in strict left-to-right order; the first identifier that does
        not correspond to an existing resource yields `ERR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/customer_get_missing_returns_not_found
        """
        resp = api.get_customer(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", OP
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestCapacityDayCreation:
    def test_capacity_day_missing_required_returns_invalid_request(self, api):
        """PRD §2.8: "the request body itself must be well-formed: required
        fields present ... Any well-formedness failure is `ERR_INVALID_REQUEST`
        (HTTP 400)."
        PRD §3.1: "supplying a `date` ... and a `capacity_head` of at least one
        animal."

        Design: Corner/entities/capacity_day_missing_required_returns_invalid_request
        """
        resp = api.create_capacity_day({"date": "2026-08-20"}, MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        days = get_success_data(
            api.list_capacity_days(OP, params={"date_from": "2026-08-20",
                                               "date_to": "2026-08-20"})
        )
        assert days == [], "rejected create must not persist a CapacityDay"

    def test_capacity_day_duplicate_date_returns_invalid_request(self, api):
        """PRD §3.1: "a `date` — an ISO 8601 calendar date that must be unique
        across all capacity days, with a duplicate rejected as
        `ERR_INVALID_REQUEST`".

        Design: Corner/entities/capacity_day_duplicate_date_returns_invalid_request
        """
        create_capacity_day("2026-08-20", 2)
        resp = api.create_capacity_day(
            create_capacity_day_payload("2026-08-20", 5), MGR
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        days = get_success_data(
            api.list_capacity_days(OP, params={"date_from": "2026-08-20",
                                               "date_to": "2026-08-20"})
        )
        assert len(days) == 1, "only one CapacityDay for 2026-08-20 may exist"


class TestBookingWellFormednessAndAuth:
    def test_appointment_unknown_field_returns_invalid_request(self, api):
        """PRD §2.8: "and no undeclared fields. Any well-formedness failure is
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/appointment_unknown_field_returns_invalid_request
        """
        customer = create_customer()
        day = create_capacity_day("2026-08-20", 1)
        payload = create_appointment_payload(customer["id"], day["id"], "BEEF", 1)
        payload["status"] = "CONFIRMED"  # undeclared field spoof
        resp = api.create_appointment(payload, make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        day_after = get_capacity_day_by_date("2026-08-20")
        assert day_after["booked_head"] == 0, (
            "rejected booking must not reserve capacity"
        )

    def test_booking_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside this enumeration, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/booking_missing_auth_headers_unauthenticated
        """
        day = create_capacity_day("2026-08-20", 1)
        payload = create_appointment_payload(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", day["id"], "BEEF", 1
        )
        resp = api.create_appointment(payload, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRoleBoundaries:
    def test_customer_cannot_create_capacity_day(self, api):
        """PRD §4: `POST /locker/capacity-days` — Authorized Role(s):
        PlantManager.
        PRD §2.1: "A request whose role is not permitted on the targeted
        endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/customer_cannot_create_capacity_day
        """
        customer = create_customer()
        resp_customer = api.create_capacity_day(
            create_capacity_day_payload("2026-08-20", 1),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp_customer, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        resp_operator = api.create_capacity_day(
            create_capacity_day_payload("2026-08-21", 1), OP
        )
        validate_error(resp_operator, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_customer_cannot_read_others_appointment(self, api):
        """PRD §2.1: "a Customer caller owns an appointment when its
        `customer_id` equals `X-User-ID`"
        PRD §2.8: "then authorization and entity-backed ownership
        (`ERR_FORBIDDEN`)".

        Design: Corner/rbac/customer_cannot_read_others_appointment
        """
        owner = create_customer("Ann Orr", "555-0101", "ann@x.com")
        other = create_customer("Bob Venn", "555-0102", "bob@x.com")
        day = create_capacity_day("2026-08-20", 1)
        appointment = book_appointment(owner["id"], day["id"], "BEEF", 1)
        resp = api.get_appointment(appointment["id"], make_customer_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


class TestAppointmentCreation:
    def test_appointment_initial_state_is_pending_deposit(self, api):
        """PRD §3.1: "A successfully created appointment lands in
        `PENDING_DEPOSIT` with `deposit_amount_cents` set to the quote,
        `deposit_paid_cents` at zero, `refund_cents` at zero,
        `appointment_date` copied from the reserved day, and `deposit_due_at`
        exactly 48 hours after the appointment's `created_at`."

        Design: Corner/state_machines/appointment_initial_state_is_pending_deposit
        """
        customer = create_customer()
        day = create_capacity_day("2026-08-20", 1)
        resp = api.create_appointment(
            create_appointment_payload(customer["id"], day["id"], "BEEF", 1),
            make_customer_headers(customer["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert_appointment(data)
        assert data["status"] == "PENDING_DEPOSIT"
        assert data["deposit_paid_cents"] == 0
        assert data["refund_cents"] == 0
        assert data["appointment_date"] == "2026-08-20"
        delta = _parse(data["deposit_due_at"]) - _parse(data["created_at"])
        assert delta.total_seconds() == 48 * 3600, (
            "deposit_due_at must be exactly 48 hours after created_at"
        )

    def test_booking_exactly_min_lead_days_allowed(self, api):
        """PRD §3.1: "the reserved date must fall at least fourteen days after
        the current date, with a date exactly fourteen days out acceptable,
        otherwise `ERR_LEAD_TIME_TOO_SHORT`".

        Design: Difficulty/boundary_precision_check/booking_exactly_min_lead_days_allowed
        """
        customer = create_customer()
        day = create_capacity_day("2026-08-15", 1)  # exactly 14 days out
        resp = api.create_appointment(
            create_appointment_payload(customer["id"], day["id"], "BEEF", 1),
            make_customer_headers(customer["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PENDING_DEPOSIT"
        assert data["appointment_date"] == "2026-08-15"

    def test_booking_thirteen_days_out_rejected(self, api):
        """PRD §3.1: "the reserved date must fall at least fourteen days after
        the current date, with a date exactly fourteen days out acceptable,
        otherwise `ERR_LEAD_TIME_TOO_SHORT`".

        Design: Difficulty/boundary_precision_check/booking_exactly_min_lead_days_allowed
        """
        customer = create_customer()
        day = create_capacity_day("2026-08-14", 1)  # only 13 days out
        resp = api.create_appointment(
            create_appointment_payload(customer["id"], day["id"], "BEEF", 1),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LEAD_TIME_TOO_SHORT, expected_status=422)


class TestCapacityAggregation:
    def test_pending_deposit_booking_holds_capacity(self, api):
        """PRD §3.1: "if the day's `booked_head` plus the requested
        `head_count` would exceed `capacity_head` — where `booked_head`
        aggregates all appointments on that day still in `PENDING_DEPOSIT` or
        `CONFIRMED` — the request fails with `ERR_CAPACITY_FULL`."

        Design: Difficulty/resource_temporal_overlap/capacity_day_head_count_aggregate_overflow
        """
        c1 = create_customer("Ann Orr", "555-0101", "ann@x.com")
        c2 = create_customer("Bob Venn", "555-0102", "bob@x.com")
        day = create_capacity_day("2026-08-20", 2)
        first = book_appointment(c1["id"], day["id"], "BEEF", 2)
        assert first["status"] == "PENDING_DEPOSIT"
        # c1's PENDING_DEPOSIT appointment already holds both heads.
        resp = api.create_appointment(
            create_appointment_payload(c2["id"], day["id"], "HOG", 1),
            make_customer_headers(c2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_FULL, expected_status=409)

    def test_capacity_freed_after_cancel(self, api):
        """PRD §3.1: "if the day's `booked_head` plus the requested
        `head_count` would exceed `capacity_head` — where `booked_head`
        aggregates all appointments on that day still in `PENDING_DEPOSIT` or
        `CONFIRMED` — the request fails with `ERR_CAPACITY_FULL`."
        PRD §3.2: "While the appointment is still `PENDING_DEPOSIT`,
        cancellation is unconditional: the day's `booked_head` is released"

        Design: Difficulty/resource_temporal_overlap/capacity_day_head_count_aggregate_overflow
        """
        c1 = create_customer("Ann Orr", "555-0101", "ann@x.com")
        c2 = create_customer("Bob Venn", "555-0102", "bob@x.com")
        day = create_capacity_day("2026-08-20", 2)
        appointment, _ = book_and_confirm(c1["id"], day["id"], "BEEF", 2)
        # Confirmed appointment still aggregates the day's full capacity.
        resp = api.create_appointment(
            create_appointment_payload(c2["id"], day["id"], "HOG", 1),
            make_customer_headers(c2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_FULL, expected_status=409)
        # Cancellation releases the head count, reopening the day.
        get_success_data(
            api.cancel_appointment(appointment["id"], make_customer_headers(c1["id"]))
        )
        data = validate_success(
            api.create_appointment(
                create_appointment_payload(c2["id"], day["id"], "HOG", 1),
                make_customer_headers(c2["id"]),
            ),
            expected_status=201,
        )
        assert data["status"] == "PENDING_DEPOSIT"
        day_after = get_capacity_day_by_date("2026-08-20")
        assert day_after["booked_head"] == 1
        assert day_after["status"] == "OPEN"


class TestBookCancelInvariant:
    def test_book_cancel_roundtrip_preserves_booked_head(self, api):
        """PRD §3.1: "A freshly opened day has `booked_head` of zero and status
        `OPEN`; the day flips to `FULL` exactly when `booked_head` reaches
        `capacity_head` and returns to `OPEN` the moment a cancellation,
        expiry, or no-show releases headroom."
        PRD §3.2: "A confirmed cancellation voids each expected animal, and
        each voided animal releases one head of capacity back to the day."

        Design: Difficulty/compensating_invariant/book_cancel_roundtrip_preserves_capacity
        """
        customer = create_customer()
        day = create_capacity_day("2026-08-20", 3)
        # Round trip 1: book 2 while PENDING_DEPOSIT, then cancel.
        first = book_appointment(customer["id"], day["id"], "BEEF", 2)
        assert get_capacity_day_by_date("2026-08-20")["booked_head"] == 2
        get_success_data(
            api.cancel_appointment(first["id"], make_customer_headers(customer["id"]))
        )
        # Round trip 2: book 3, confirm, then cancel.
        second, _ = book_and_confirm(customer["id"], day["id"], "BEEF", 3)
        get_success_data(
            api.cancel_appointment(second["id"], make_customer_headers(customer["id"]))
        )
        day_after = get_capacity_day_by_date("2026-08-20")
        assert day_after["booked_head"] == 0, (
            "booked_head must return to zero after both cancel round trips"
        )
        assert day_after["status"] == "OPEN"

    def test_cancel_refund_pending_zero_confirmed_full(self, api):
        """PRD §3.2: "While the appointment is still `PENDING_DEPOSIT`,
        cancellation is unconditional: the day's `booked_head` is released,
        `refund_cents` is set to whatever deposit cash has been received —
        normally zero, since any successful deposit payment would already have
        confirmed the booking — and the appointment becomes `CANCELLED`."
        PRD §3.2: "if the whole-day count from the current date to
        `appointment_date` is at least seven, `refund_cents` is the full
        `deposit_paid_cents`".

        Design: Difficulty/compensating_invariant/book_cancel_roundtrip_preserves_capacity
        """
        customer = create_customer()
        day = create_capacity_day("2026-08-20", 3)
        # PENDING_DEPOSIT cancel: nothing paid, refund is zero.
        pending = book_appointment(customer["id"], day["id"], "BEEF", 2)
        cancelled_pending = validate_success(
            api.cancel_appointment(pending["id"], make_customer_headers(customer["id"]))
        )
        assert cancelled_pending["status"] == "CANCELLED"
        assert cancelled_pending["refund_cents"] == 0
        # CONFIRMED cancel 19 days out (>= 7): full deposit refunded.
        confirmed, _ = book_and_confirm(customer["id"], day["id"], "BEEF", 3)
        cancelled_confirmed = validate_success(
            api.cancel_appointment(confirmed["id"], make_customer_headers(customer["id"]))
        )
        assert cancelled_confirmed["status"] == "CANCELLED"
        assert cancelled_confirmed["refund_cents"] == 45000


class TestRescheduleSelfLoop:
    def test_reschedule_self_loop_keeps_status_and_updates_date(self, api):
        """PRD §3.2: "Rescheduling is a self-loop available from both
        `PENDING_DEPOSIT` and `CONFIRMED`: the appointment's status does not
        change, only its calendar placement."
        PRD §3.2: "`appointment_date` is rewritten to the new day's date."

        Design: Difficulty/non_linear_state_machine/appointment_reschedule_self_loop_with_capacity_rebalance
        """
        customer = create_customer()
        day1 = create_capacity_day("2026-08-20", 2)
        day2 = create_capacity_day("2026-08-21", 2)
        appointment, _ = book_and_confirm(customer["id"], day1["id"], "BEEF", 2)
        version_before = appointment["version"]
        data = validate_success(
            api.reschedule_appointment(
                appointment["id"],
                reschedule_payload(day2["id"], version_before),
                make_customer_headers(customer["id"]),
            )
        )
        assert data["status"] == "CONFIRMED", "self-loop must not change status"
        assert data["appointment_date"] == "2026-08-21"
        assert data["version"] == version_before + 1, (
            "version increments by exactly 1 on every mutation (PRD §2.5)"
        )

    def test_reschedule_rebalances_capacity_days(self, api):
        """PRD §3.2: "On success the old day's `booked_head` decreases by
        `head_count`, the new day's increases by the same amount (recomputing
        each day's `OPEN` or `FULL` standing)".
        PRD §3.1: "the day flips to `FULL` exactly when `booked_head` reaches
        `capacity_head` and returns to `OPEN` the moment a cancellation,
        expiry, or no-show releases headroom."

        Design: Difficulty/non_linear_state_machine/appointment_reschedule_self_loop_with_capacity_rebalance
        """
        customer = create_customer()
        day1 = create_capacity_day("2026-08-20", 2)
        day2 = create_capacity_day("2026-08-21", 2)
        appointment, _ = book_and_confirm(customer["id"], day1["id"], "BEEF", 2)
        assert get_capacity_day_by_date("2026-08-20")["status"] == "FULL"
        validate_success(
            api.reschedule_appointment(
                appointment["id"],
                reschedule_payload(day2["id"], appointment["version"]),
                make_customer_headers(customer["id"]),
            )
        )
        old_day = get_capacity_day_by_date("2026-08-20")
        new_day = get_capacity_day_by_date("2026-08-21")
        assert old_day["booked_head"] == 0 and old_day["status"] == "OPEN"
        assert new_day["booked_head"] == 2 and new_day["status"] == "FULL"

    def test_occ_stale_reschedule_rejected_412(self, api):
        """PRD §2.7: "Rescheduling an appointment requires the request to carry
        `expected_appointment_version` holding the appointment's current
        `version` as last observed by the client ... and a request whose value
        does not match the appointment's current `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_reschedule_rejected_412
        """
        customer = create_customer()
        day1 = create_capacity_day("2026-08-20", 1)
        day2 = create_capacity_day("2026-08-21", 1)
        appointment, _ = book_and_confirm(customer["id"], day1["id"], "BEEF", 1)
        current_version = appointment["version"]
        # Stale version: rejected with 412 and the appointment is unmoved.
        stale = api.reschedule_appointment(
            appointment["id"],
            reschedule_payload(day2["id"], current_version - 1),
            make_customer_headers(customer["id"]),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        unmoved = get_appointment(appointment["id"])
        assert unmoved["appointment_date"] == "2026-08-20"
        assert unmoved["version"] == current_version
        # Current version: succeeds and moves the booking.
        data = validate_success(
            api.reschedule_appointment(
                appointment["id"],
                reschedule_payload(day2["id"], current_version),
                make_customer_headers(customer["id"]),
            )
        )
        assert data["appointment_date"] == "2026-08-21"
        assert data["version"] == current_version + 1

    def test_reschedule_to_too_soon_day_rejected(self, api):
        """PRD §3.2: "The target day must exist, its date must satisfy the same
        fourteen-day lead rule, and it must have room for the booking's
        `head_count`; the same `ERR_NOT_FOUND`, `ERR_LEAD_TIME_TOO_SHORT`, and
        `ERR_CAPACITY_FULL` rejections apply in their usual order."

        Design: Corner/validations/reschedule_to_too_soon_day_rejected
        """
        customer = create_customer()
        day1 = create_capacity_day("2026-08-20", 1)
        day2 = create_capacity_day("2026-08-10", 1)  # only 9 days out
        appointment, _ = book_and_confirm(customer["id"], day1["id"], "BEEF", 1)
        resp = api.reschedule_appointment(
            appointment["id"],
            reschedule_payload(day2["id"], appointment["version"]),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LEAD_TIME_TOO_SHORT, expected_status=422)
        unchanged = get_appointment(appointment["id"])
        assert unchanged["status"] == "CONFIRMED"
        assert unchanged["appointment_date"] == "2026-08-20"


class TestCapacityDayListing:
    def test_capacity_day_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned:
        it defaults to 10 when omitted, accepts a minimum of 1, and rejects
        values above 100. The `offset` parameter skips a number of items from
        the front of the result set and defaults to 0."
        PRD §2.3: "The `meta` object of every list response carries the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/capacity_day_list_pagination_envelope
        """
        create_capacity_day("2026-08-20", 1)
        create_capacity_day("2026-08-21", 1)
        create_capacity_day("2026-08-22", 1)
        page1 = api.list_capacity_days(OP, params={"limit": 2, "offset": 0})
        data1, meta1 = validate_paginated(page1)
        assert len(data1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0
        assert isinstance(meta1.get("api_request_id"), str)
        assert isinstance(meta1.get("api_request_timestamp"), str)
        page2 = api.list_capacity_days(OP, params={"limit": 2, "offset": 2})
        data2, meta2 = validate_paginated(page2)
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        for row in data1 + data2:
            assert_capacity_day(row)
