"""Booking creation: window discipline, pool rules, walk-in semantics, the
create-response contract, and booking list filters."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_booking,
    create_booking_payload,
    create_reserved_booking,
    create_site_with_stalls,
    create_walkin_booking,
    make_driver_headers,
    register_driver,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestWindowDiscipline:

    def test_window_too_long_rejected(self):
        """PRD section 2.7: "Window values on booking creation and waitlist
        joins (all 422): a `RESERVED` arrival before the clock date is
        `ERR_WINDOW_IN_PAST`; a `WALK_IN` arrival that is not exactly the
        clock date is `ERR_WALKIN_NOT_TODAY`; a `night_count` above 14 is
        `ERR_WINDOW_TOO_LONG`; an unparseable `arrival_date` or a
        `night_count` below 1 is `ERR_WINDOW_INVALID`."

        Design: Corner/validations/window_too_long_rejected
        """
        ctx = create_site_with_stalls(num_reservable=1)
        driver = register_driver("CDL-WL-1", "W Ell")
        set_clock("2026-08-01T00:00:00Z")

        resp = api_client.create_booking(
            create_booking_payload(driver["id"], ctx["site"]["id"],
                                   "2026-08-10", night_count=15),
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_TOO_LONG)

        resp = api_client.create_booking(
            create_booking_payload(driver["id"], ctx["site"]["id"],
                                   "2026-08-10", night_count=14),
            make_driver_headers(driver["id"]),
        )
        ok = validate_success(resp, expected_status=201)
        assert_booking(ok)
        assert ok["night_count"] == 14

    def test_walkin_arrival_not_today_rejected(self):
        """PRD section 3.4: "a `WALK_IN` booking's `arrival_date` must equal
        the clock date exactly (`ERR_WALKIN_NOT_TODAY`)".

        Design: Corner/validations/walkin_arrival_not_today_rejected
        """
        ctx = create_site_with_stalls(num_reservable=0, num_first_come=1)
        driver = register_driver("CDL-WT-1", "W Tee")
        set_clock("2026-08-01T18:00:00Z")

        resp = api_client.create_booking(
            create_booking_payload(driver["id"], ctx["site"]["id"],
                                   "2026-08-02", booking_kind="WALK_IN"),
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WALKIN_NOT_TODAY)

    def test_reserved_arrival_in_past_rejected(self):
        """PRD section 3.4: "A `RESERVED` booking's `arrival_date` must not
        fall before the clock date (`ERR_WINDOW_IN_PAST`)".

        Design: Corner/validations/reserved_arrival_in_past_rejected
        """
        ctx = create_site_with_stalls(num_reservable=1)
        driver = register_driver("CDL-PW-1", "P Dub")
        set_clock("2026-08-10T00:00:00Z")

        resp = api_client.create_booking(
            create_booking_payload(driver["id"], ctx["site"]["id"],
                                   "2026-08-09"),
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST)

        resp = api_client.create_booking(
            create_booking_payload(driver["id"], ctx["site"]["id"],
                                   "2026-08-10"),
            make_driver_headers(driver["id"]),
        )
        ok = validate_success(resp, expected_status=201)
        assert ok["status"] == "BOOKED", \
            "arrival equal to the clock date is allowed"

    def test_night_count_zero_and_inverted_availability_window_rejected(self):
        """PRD section 2.7: "an unparseable `arrival_date` or a `night_count`
        below 1 is `ERR_WINDOW_INVALID`."
        PRD section 3.2: "a window whose start is not before its end is
        rejected with `ERR_WINDOW_INVALID`."

        Design: Corner/validations/night_count_zero_and_inverted_availability_window_rejected
        """
        ctx = create_site_with_stalls(num_reservable=1)
        site = ctx["site"]
        driver = register_driver("CDL-WI-1", "W Eye")
        set_clock("2026-08-01T00:00:00Z")

        resp = api_client.create_booking(
            create_booking_payload(driver["id"], site["id"], "2026-08-10",
                                   night_count=0),
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_INVALID)

        resp = api_client.get_site_availability(
            site["id"], ADMIN,
            params={"window_start": "2026-08-10T15:00:00Z",
                    "window_end": "2026-08-10T15:00:00Z"})
        validate_error(resp, ApiErrorId.ERR_WINDOW_INVALID)


class TestPoolAndConflictRules:

    def test_driver_overlapping_booking_rejected(self):
        """PRD section 3.4: "The same driver may not hold two overlapping
        non-terminal bookings anywhere (`ERR_DRIVER_WINDOW_CONFLICT`)."

        Design: Corner/validations/driver_overlapping_booking_rejected
        """
        ctx = create_site_with_stalls(num_reservable=2)
        driver = register_driver("CDL-DO-1", "D Oh")
        set_clock("2026-08-01T00:00:00Z")
        create_reserved_booking(driver["id"], ctx["site"]["id"],
                                "2026-08-10", 1)

        resp = api_client.create_booking(
            create_booking_payload(driver["id"], ctx["site"]["id"],
                                   "2026-08-10"),
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DRIVER_WINDOW_CONFLICT)

    def test_reserved_pool_exhausted_rejected(self):
        """PRD section 3.4: "When the eligible set is empty, creation fails
        with `ERR_SITE_CAPACITY_FULL` for both kinds."

        Design: Corner/validations/reserved_pool_exhausted_rejected
        """
        ctx = create_site_with_stalls(num_reservable=1)
        site = ctx["site"]
        first = register_driver("CDL-CA-1", "C Aye")
        second = register_driver("CDL-CB-1", "C Bee")
        set_clock("2026-08-01T00:00:00Z")
        create_reserved_booking(first["id"], site["id"], "2026-08-10", 1)

        resp = api_client.create_booking(
            create_booking_payload(second["id"], site["id"], "2026-08-10"),
            make_driver_headers(second["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SITE_CAPACITY_FULL)

    def test_reserved_booking_on_first_come_stall_rejected(self):
        """PRD section 3.4: "An explicitly supplied `stall_id` is validated
        against the same pool, class, and site rules, with mismatches rejected
        as `ERR_STALL_NOT_RESERVABLE` and window conflicts as
        `ERR_STALL_WINDOW_CONFLICT`."

        Design: Corner/validations/reserved_booking_on_first_come_stall_rejected
        """
        ctx = create_site_with_stalls(num_reservable=0, num_first_come=1)
        first_come_stall = ctx["first_come"][0]
        driver = register_driver("CDL-NR-1", "N Arr")
        set_clock("2026-08-01T00:00:00Z")

        resp = api_client.create_booking(
            create_booking_payload(driver["id"], ctx["site"]["id"],
                                   "2026-08-10",
                                   stall_id=first_come_stall["id"]),
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALL_NOT_RESERVABLE)


class TestWalkInSemantics:

    def test_walkin_enters_checked_in_at_flat_base_rate(self):
        """PRD section 3.4: "A `WALK_IN` creation instead lands directly in
        `CHECKED_IN`, with check-in implicit in the walk-in act, and pins every
        night at the flat `base_nightly_rate_cents`: walk-ins receive no
        occupancy or peak multiplier, no loyalty discount, and no bundle
        discount at settlement."
        PRD section 3.2: "The night's rate is the site's
        `base_nightly_rate_cents` multiplied by the occupancy multiplier and
        by the peak factor, rounded half up to whole cents, and each night is
        rounded individually before any summation."

        Design: Corner/state_machines/walkin_enters_checked_in_at_flat_base_rate
        """
        ctx = create_site_with_stalls(num_reservable=1, num_first_come=1)
        site = ctx["site"]
        first_come_stall = ctx["first_come"][0]
        reserved_driver = register_driver("CDL-W1-1", "W One")
        walkin_driver = register_driver("CDL-W2-1", "W Two")
        set_clock("2026-08-01T00:00:00Z")
        reserved = create_reserved_booking(reserved_driver["id"], site["id"],
                                           "2026-08-14", 1)
        assert reserved["quoted_total_cents"] == 5400, (
            f"reserved quote for a Friday night: rhu(5000 * 0.9 * 1.2), got "
            f"{reserved['quoted_total_cents']}"
        )

        set_clock("2026-08-14T18:00:00Z")
        walkin = create_walkin_booking(walkin_driver["id"], site["id"],
                                       "2026-08-14", 1)
        assert_booking(walkin)
        assert walkin["status"] == "CHECKED_IN", \
            "walk-in lands directly in CHECKED_IN"
        assert walkin["stall_id"] == first_come_stall["id"], \
            "walk-ins draw from the first-come pool"
        assert walkin["quoted_total_cents"] == 5000, (
            f"walk-in pins the flat base rate with no multipliers, got "
            f"{walkin['quoted_total_cents']}"
        )


class TestCreateResponseContract:

    def test_booking_create_response_carries_full_assignment_and_quote(self):
        """PRD section 2.2: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource object
        in the data field."
        PRD section 3.4: "Among the eligible stalls the winner is the smallest
        `stall_number` in lexicographic order; because `stall_number` is unique
        per site, no further tie-break exists."
        PRD section 3.4: "A successful `RESERVED` creation lands in `BOOKED`
        with `billing_status` `UNBILLED` — every new booking starts `UNBILLED`
        — and with its `per_night_rates` pinned — a list pairing each night's
        date with its dynamically priced `rate_cents`".
        PRD section 2.5: "`version` — an integer initialized to 1 and
        incremented by exactly one on every mutation".

        Design: Corner/consistency_model/booking_create_response_carries_full_assignment_and_quote
        """
        ctx = create_site_with_stalls(num_reservable=2)
        site, stall_r01 = ctx["site"], ctx["reservable"][0]
        driver = register_driver("CDL-IC-1", "I Cee")
        set_clock("2026-08-01T00:00:00Z")

        booking = create_reserved_booking(driver["id"], site["id"],
                                          "2026-08-10", 2)
        assert_booking(booking)
        assert booking["stall_id"] == stall_r01["id"], \
            "the lowest stall_number wins assignment"
        assert booking["status"] == "BOOKED"
        assert booking["billing_status"] == "UNBILLED"
        assert booking["version"] == 1
        assert booking["quoted_total_cents"] == 9000, (
            f"2 nights x 4500 at 0% occupancy, got "
            f"{booking['quoted_total_cents']}"
        )
        rates = booking["per_night_rates"]
        assert [r["date"] for r in rates] == ["2026-08-10", "2026-08-11"]
        assert [r["rate_cents"] for r in rates] == [4500, 4500], \
            "per-night rates are pinned in the create response itself"

    def test_get_bookings_filtered_by_driver_reverse_reachability(self):
        """PRD section 3.4: "Bookings a driver never showed for,
        system-cancelled bookings, and stays in progress are all reachable
        through the booking list, which filters on `driver_id`, `site_id`,
        `stall_id`, `waitlist_entry_id`, `fleet_account_id`, `status`, and
        `billing_status`".

        Design: Corner/endpoints/get_bookings_filtered_by_driver_reverse_reachability
        """
        ctx = create_site_with_stalls(num_reservable=2)
        site = ctx["site"]
        driver_x = register_driver("CDL-FX-1", "F Ex")
        driver_y = register_driver("CDL-FY-1", "F Wye")
        set_clock("2026-08-01T00:00:00Z")
        booking_x = create_reserved_booking(driver_x["id"], site["id"],
                                            "2026-08-10", 1)
        create_reserved_booking(driver_y["id"], site["id"], "2026-08-11", 1)

        data, meta = validate_paginated(
            api_client.list_bookings(ADMIN,
                                     params={"driver_id": driver_x["id"]}))
        assert meta["total_count"] == 1, \
            f"exactly one booking belongs to driver X, got {meta['total_count']}"
        assert len(data) == 1
        assert data[0]["id"] == booking_x["id"]
