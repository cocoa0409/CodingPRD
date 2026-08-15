"""The waitlist: offer pinning, expiry and re-offer, promotion, expiry
rejection, and the one-active-entry rule."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_waitlist_entry,
    create_reserved_booking,
    create_site_with_stalls,
    create_waitlist_entry_payload,
    make_driver_headers,
    register_driver,
    run_site_ops,
    set_clock,
    setup_offered_waitlist_entry,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOfferExpiryAndReoffer:

    def test_waitlist_offer_expiry_reoffers_next_in_queue(self):
        """PRD section 3.7: "The winner moves `QUEUED` → `OFFERED` with
        `offered_stall_id` pinning the freed stall and `offer_expires_at` set
        30 minutes out."
        PRD section 3.7: "An offer left standing dies in the ops sweep: once
        the clock is strictly past `offer_expires_at`, the entry becomes
        `EXPIRED` and the pinned stall is immediately re-offered to the next
        selector winner, if any."
        PRD section 3.7: "Candidates rank by loyalty tier descending
        (`PLATINUM` above `GOLD` above `SILVER` above `STANDARD`), ties broken
        by `created_at` ascending".

        Design: Corner/state_machines/waitlist_offer_expiry_reoffers_next_in_queue
        """
        ctx = create_site_with_stalls(num_reservable=1)
        site, stall = ctx["site"], ctx["reservable"][0]
        owner = register_driver("CDL-QA-1", "Q A")
        w1 = register_driver("CDL-Q1-1", "Q One")
        w2 = register_driver("CDL-Q2-1", "Q Two")
        set_clock("2026-08-01T00:00:00Z")
        owner_booking = create_reserved_booking(owner["id"], site["id"],
                                                "2026-08-10", 1)
        e1 = validate_success(
            api_client.create_waitlist_entry(
                create_waitlist_entry_payload(w1["id"], site["id"],
                                              "2026-08-10"),
                make_driver_headers(w1["id"])),
            expected_status=201)
        e2 = validate_success(
            api_client.create_waitlist_entry(
                create_waitlist_entry_payload(w2["id"], site["id"],
                                              "2026-08-10"),
                make_driver_headers(w2["id"])),
            expected_status=201)

        resp = api_client.cancel_booking(owner_booking["id"],
                                         make_driver_headers(owner["id"]))
        validate_success(resp, expected_status=200)

        resp = api_client.get_waitlist_entry(e1["id"], ADMIN)
        e1_offered = validate_success(resp)
        assert e1_offered["status"] == "OFFERED", \
            "the first QUEUED entry (created_at tie-break) receives the offer"
        assert e1_offered["offered_stall_id"] == stall["id"]
        resp = api_client.get_waitlist_entry(e2["id"], ADMIN)
        assert validate_success(resp)["status"] == "QUEUED"

        set_clock("2026-08-01T00:31:00Z")
        run_site_ops(site["id"])

        resp = api_client.get_waitlist_entry(e1["id"], ADMIN)
        assert validate_success(resp)["status"] == "EXPIRED", \
            "clock 00:31 is strictly past the 00:30 expiry"
        resp = api_client.get_waitlist_entry(e2["id"], ADMIN)
        e2_offered = validate_success(resp)
        assert e2_offered["status"] == "OFFERED", \
            "the stall is immediately re-offered to the next winner"
        assert e2_offered["offered_stall_id"] == stall["id"]


class TestAcceptance:

    def test_waitlist_accept_promotes_and_creates_booking(self):
        """PRD section 3.7: "Acceptance moves the entry `OFFERED` → `PROMOTED`
        and materializes a booking with `booking_kind` `RESERVED`, the offered
        stall as its `stall_id`, its `waitlist_entry_id` pointing back at the
        entry, the entry's window, per-night rates quoted at the current
        dynamic rate, and status `BOOKED`."

        Design: Corner/state_machines/waitlist_accept_promotes_and_creates_booking
        """
        ctx = setup_offered_waitlist_entry()
        entry = ctx["entry"]
        waiter = ctx["waiter_driver"]

        resp = api_client.accept_waitlist_entry(
            entry["id"], make_driver_headers(waiter["id"]))
        promoted = validate_success(resp, expected_status=200)
        assert promoted["status"] == "PROMOTED"
        assert_waitlist_entry(promoted)

        data, meta = validate_paginated(
            api_client.list_bookings(ADMIN,
                                     params={"waitlist_entry_id": entry["id"]}))
        assert meta["total_count"] == 1, \
            "exactly one booking materializes from the promotion"
        booking = data[0]
        assert booking["status"] == "BOOKED"
        assert booking["booking_kind"] == "RESERVED"
        assert booking["stall_id"] == ctx["stall"]["id"]
        assert booking["quoted_total_cents"] == 4500, (
            f"quoted at the current dynamic rate (0% occupancy after the "
            f"cancellation): got {booking['quoted_total_cents']}"
        )

    def test_waitlist_accept_after_offer_expiry_rejected(self):
        """PRD section 3.7: "the clock must be at or before `offer_expires_at`
        — an inclusive boundary, with later attempts rejected
        `ERR_OFFER_EXPIRED` if the sweep has not already expired the entry".

        Design: Corner/validations/waitlist_accept_after_offer_expiry_rejected
        """
        ctx = setup_offered_waitlist_entry()
        entry = ctx["entry"]
        waiter = ctx["waiter_driver"]

        set_clock("2026-08-01T00:30:01Z")
        resp = api_client.accept_waitlist_entry(
            entry["id"], make_driver_headers(waiter["id"]))
        validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)

        resp = api_client.get_waitlist_entry(entry["id"], ADMIN)
        after = validate_success(resp)
        assert after["status"] == "OFFERED", \
            "no sweep has run, so the entry is still OFFERED"


class TestOneActiveEntryPerSite:

    def test_duplicate_waitlist_entry_rejected(self):
        """PRD section 3.7: "a driver may hold at most one `QUEUED` or
        `OFFERED` entry per site — a second active entry is
        `ERR_DUPLICATE_WAITLIST_ENTRY`."

        Design: Corner/endpoints/duplicate_waitlist_entry_rejected
        """
        ctx = create_site_with_stalls(num_reservable=1)
        site = ctx["site"]
        driver = register_driver("CDL-DW-1", "D Dub")
        set_clock("2026-08-01T00:00:00Z")
        first = validate_success(
            api_client.create_waitlist_entry(
                create_waitlist_entry_payload(driver["id"], site["id"],
                                              "2026-08-10"),
                make_driver_headers(driver["id"])),
            expected_status=201)
        assert first["status"] == "QUEUED"

        resp = api_client.create_waitlist_entry(
            create_waitlist_entry_payload(driver["id"], site["id"],
                                          "2026-08-11"),
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_WAITLIST_ENTRY)
