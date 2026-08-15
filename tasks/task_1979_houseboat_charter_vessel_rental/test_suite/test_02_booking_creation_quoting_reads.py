"""Booking creation: payload rules, date/rate/berth gates, quote arithmetic,
parallel-dimension initial state, and the booking read surface."""
from datetime import datetime, timedelta, timezone

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_booking,
    create_booking,
    create_qualified_renter,
    create_season_rate,
    create_vessel,
    register_renter,
    setup_confirmed_booking,
    setup_fleet_with_rate,
    submit_certificate,
    validate_error,
    validate_paginated,
    validate_success,
    verify_certificate,
)

FM = TEST_USERS["fleet_manager_headers"]
DS = TEST_USERS["dock_staff_headers"]


def _parse_iso(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestCreationPayloadRules:
    def test_booking_create_missing_required_end_date(self, api):
        """PRD §2.11: "Body well-formedness — missing required fields, type
        mismatches, unknown enum members, an unknown orientation `item_code`,
        empty `zone_ids`, a window whose end does not follow its start, a
        duplicate `zone_code`, or an `occurred_at` in the future or before the
        booking's start: `ERR_INVALID_REQUEST`."
        PRD §3.4: "A `Renter` opens a booking with a payload naming the
        `vessel_id`, their own `renter_id` (which must equal `X-User-ID`, else
        `ERR_NOT_RESOURCE_OWNER`), the desired `start_date` and `end_date`, and
        the `party_size`."

        Design: Corner/entities/booking_create_missing_required_end_date
        """
        vessel = setup_fleet_with_rate()
        renter, headers, _ = create_qualified_renter(
            full_name="Rea Quired", email="req@x.com", cert_number="CERT-0002")

        resp = api.create_booking(
            {
                "vessel_id": vessel["id"],
                "renter_id": renter["id"],
                "start_date": "2026-08-20",
                "party_size": 2,
            },
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_booking_computed_fields_input_ignored(self, api):
        """PRD §3.4: "The quote is computed night by night over the half-open
        stay."
        PRD §3.4: "`quoted_total_cents` is the subtotal minus the sum of the
        per-window discounts."
        PRD §3.4: "A `Renter` opens a booking with a payload naming the
        `vessel_id`, their own `renter_id` (which must equal `X-User-ID`, else
        `ERR_NOT_RESOURCE_OWNER`), the desired `start_date` and `end_date`, and
        the `party_size`."

        Design: Corner/entities/booking_computed_fields_input_ignored
        """
        vessel = setup_fleet_with_rate()
        renter, headers, _ = create_qualified_renter(
            full_name="Ina Put", email="ina@x.com", cert_number="CERT-0003")

        resp = api.create_booking(
            {
                "vessel_id": vessel["id"],
                "renter_id": renter["id"],
                "start_date": "2026-08-20",
                "end_date": "2026-08-24",
                "party_size": 2,
                "quoted_total_cents": 1,
            },
            headers,
        )
        booking = validate_success(resp, 201)
        assert booking["quoted_total_cents"] == 180000, (
            "server computes 4 nights x 45000 with no complete 7-night run; "
            f"client-injected value ignored, got {booking['quoted_total_cents']}"
        )


class TestCreationBusinessGates:
    def test_booking_dates_invalid_rejected(self, api):
        """PRD §3.4: "`end_date` must follow `start_date`, the stay must not
        exceed 21 nights, and `start_date` must not lie in the past
        (`ERR_BOOKING_DATES_INVALID`)"
        PRD §2.9: "A single booking may span at most 21 nights."

        Design: Corner/validations/booking_dates_invalid_rejected
        """
        vessel = setup_fleet_with_rate()
        renter, headers, _ = create_qualified_renter(
            full_name="Dat Es", email="dates@x.com", cert_number="CERT-0004")

        resp = api.create_booking(
            {
                "vessel_id": vessel["id"],
                "renter_id": renter["id"],
                "start_date": "2026-08-22",
                "end_date": "2026-08-20",
                "party_size": 2,
            },
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_DATES_INVALID, 422)

        resp = api.create_booking(
            {
                "vessel_id": vessel["id"],
                "renter_id": renter["id"],
                "start_date": "2026-08-01",
                "end_date": "2026-09-01",
                "party_size": 2,
            },
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_DATES_INVALID, 422)

    def test_party_exceeds_berth_rejected(self, api):
        """PRD §3.4: "and `party_size` must be at least 1 and no more than the
        vessel's `berth_count` (`ERR_PARTY_EXCEEDS_BERTH`)"

        Design: Corner/validations/party_exceeds_berth_rejected
        """
        vessel = setup_fleet_with_rate(berth=6)
        renter, headers, _ = create_qualified_renter(
            full_name="Par Ty", email="party@x.com", cert_number="CERT-0005")

        resp = api.create_booking(
            {
                "vessel_id": vessel["id"],
                "renter_id": renter["id"],
                "start_date": "2026-08-20",
                "end_date": "2026-08-22",
                "party_size": 7,
            },
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_PARTY_EXCEEDS_BERTH, 422)

        ok = api.create_booking(
            {
                "vessel_id": vessel["id"],
                "renter_id": renter["id"],
                "start_date": "2026-08-20",
                "end_date": "2026-08-22",
                "party_size": 6,
            },
            headers,
        )
        booking = validate_success(ok, 201)
        assert booking["party_size"] == 6, "party_size == berth_count is legal"

    def test_rate_not_configured_gap_night(self, api):
        """PRD §3.4: "every night of the stay must be covered by a season rate
        of the vessel's size class (`ERR_RATE_NOT_CONFIGURED`)"

        Design: Corner/validations/rate_not_configured_gap_night
        """
        vessel = setup_fleet_with_rate()  # PEAK window ends 2026-08-31
        renter, headers, _ = create_qualified_renter(
            full_name="Gap Night", email="gap@x.com", cert_number="CERT-0006")

        resp = api.create_booking(
            {
                "vessel_id": vessel["id"],
                "renter_id": renter["id"],
                "start_date": "2026-09-01",
                "end_date": "2026-09-04",
                "party_size": 2,
            },
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_RATE_NOT_CONFIGURED, 422)

    def test_create_booking_safety_beats_temporal(self, api):
        """PRD §2.11: "Within the booking creation / confirmation /
        modification family, the business checks fire in this sequence: renter
        qualification (`ERR_RENTER_NOT_QUALIFIED`) first, then booking date
        sanity (`ERR_BOOKING_DATES_INVALID`), then the half-open vessel overlap
        (`ERR_VESSEL_DATE_CONFLICT`), then the closed-interval maintenance
        conflict (`ERR_MAINTENANCE_DATE_CONFLICT`), then season-rate coverage
        (`ERR_RATE_NOT_CONFIGURED`), and finally party size
        (`ERR_PARTY_EXCEEDS_BERTH`)."

        Design: Difficulty/priority_pair_validation_conflict/create_booking_safety_beats_temporal
        """
        vessel = setup_fleet_with_rate(size_class="STANDARD_44", tank=200)
        r1, h1, _ = create_qualified_renter(
            full_name="Pat One", email="pat@x.com", cert_number="CERT-0007")
        blocking = create_booking(vessel["id"], r1, h1,
                                  start_date="2026-08-10", end_date="2026-08-15")
        get = validate_success(api.confirm_booking(blocking["id"], h1), 200)
        assert get["status"] == "CONFIRMED"

        # R2 never submitted a certificate -> UNVERIFIED; the requested stay
        # also overlaps the CONFIRMED booking. Qualification must surface.
        r2, h2 = register_renter(full_name="Pat Two", email="pat2@x.com",
                                 date_of_birth="1995-07-07")
        resp = api.create_booking(
            {
                "vessel_id": vessel["id"],
                "renter_id": r2["id"],
                "start_date": "2026-08-12",
                "end_date": "2026-08-14",
                "party_size": 2,
            },
            h2,
        )
        validate_error(resp, ApiErrorId.ERR_RENTER_NOT_QUALIFIED, 422)

    def test_unqualified_create_alone_errors(self, api):
        """PRD §3.4: "the renter must be `QUALIFIED` and hold at least one
        `VERIFIED` certificate whose `expires_on` reaches the booking's
        `end_date` (`ERR_RENTER_NOT_QUALIFIED`)"

        Design: Difficulty/priority_pair_validation_conflict/create_booking_safety_beats_temporal
        """
        vessel = setup_fleet_with_rate(size_class="STANDARD_44", tank=200)
        r2, h2 = register_renter(full_name="Pat Three", email="pat3@x.com",
                                 date_of_birth="1995-07-08")
        resp = api.create_booking(
            {
                "vessel_id": vessel["id"],
                "renter_id": r2["id"],
                "start_date": "2026-08-20",
                "end_date": "2026-08-22",
                "party_size": 2,
            },
            h2,
        )
        validate_error(resp, ApiErrorId.ERR_RENTER_NOT_QUALIFIED, 422)


class TestQuoteArithmetic:
    def test_quote_single_season_weekly_discount_exact(self, api):
        """PRD §3.4: "The weekly discount is then computed per rate window
        independently: for each window touched by the stay, count the nights of
        the stay falling within that window's closed interval, take the
        complete 7-night runs in that count (the count divided by 7, rounded
        down), and discount each run by seven times the window's nightly rate
        times its whole-percent `weekly_discount_pct` divided by 100."

        Design: Corner/calculations/quote_single_season_weekly_discount_exact
        """
        vessel = setup_fleet_with_rate(size_class="STANDARD_44", tank=200)
        renter, headers, _ = create_qualified_renter(
            full_name="Quo Te", email="quo@x.com", cert_number="CERT-0008")

        booking = create_booking(vessel["id"], renter, headers,
                                 start_date="2026-08-10", end_date="2026-08-17")
        assert booking["total_nights"] == 7
        assert booking["quoted_total_cents"] == 409500, (
            "7 x 65000 = 455000 minus one weekly run 7 x 65000 x 10% = 45500; "
            f"got {booking['quoted_total_cents']}"
        )

    def test_quote_season_split_weekly_runs(self, api):
        """PRD §3.4: "Weekly runs never span a season boundary: a 15-night stay
        split 4 nights into one window and 11 into the next earns no discounted
        run in the first window (4 nights hold no complete run of 7) and
        exactly one discounted run in the second (11 nights hold one run
        of 7)."

        Design: Difficulty/combinatorial_formula/quote_season_split_weekly_runs
        """
        vessel = create_vessel(name="Luxe Two", size_class="LUXE_56",
                               berth_count=8, fuel_tank_capacity_gallons=300)
        create_season_rate(size_class="LUXE_56", season="PEAK",
                           start_date="2026-06-01", end_date="2026-08-31",
                           nightly_rate_cents=90000, weekly_discount_pct=10)
        create_season_rate(size_class="LUXE_56", season="SHOULDER",
                           start_date="2026-09-01", end_date="2026-10-31",
                           nightly_rate_cents=65000, weekly_discount_pct=10)
        renter, headers, _ = create_qualified_renter(
            full_name="Quinn Split", email="quinn@x.com", cert_number="C-300",
            issuing_authority="STATE", cert_issued_on="2026-03-01")

        booking = create_booking(vessel["id"], renter, headers,
                                 start_date="2026-08-28", end_date="2026-09-12",
                                 party_size=4)
        assert booking["total_nights"] == 15
        # 4 PEAK x 90000 + 11 SHOULDER x 65000 = 1075000; only the SHOULDER
        # side holds a full run: floor(11/7) x 7 x 65000 x 10% = 45500.
        assert booking["quoted_total_cents"] == 1029500, (
            f"expected 1029500 (1075000 - 45500), got {booking['quoted_total_cents']}"
        )

    def test_weekly_run_requires_full_seven_nights(self, api):
        """PRD §3.4: "The weekly discount is then computed per rate window
        independently: for each window touched by the stay, count the nights of
        the stay falling within that window's closed interval, take the
        complete 7-night runs in that count (the count divided by 7, rounded
        down), and discount each run by seven times the window's nightly rate
        times its whole-percent `weekly_discount_pct` divided by 100."

        Design: Difficulty/combinatorial_formula/quote_season_split_weekly_runs
        """
        vessel = create_vessel(name="Luxe Nine", size_class="LUXE_56",
                               berth_count=8, fuel_tank_capacity_gallons=300)
        create_season_rate(size_class="LUXE_56", season="SHOULDER",
                           start_date="2026-09-01", end_date="2026-10-31",
                           nightly_rate_cents=65000, weekly_discount_pct=10)
        renter, headers, _ = create_qualified_renter(
            full_name="Run Seven", email="run7@x.com", cert_number="CERT-0009")

        six = create_booking(vessel["id"], renter, headers,
                             start_date="2026-09-01", end_date="2026-09-07")
        assert six["total_nights"] == 6
        assert six["quoted_total_cents"] == 390000, (
            "floor(6/7) = 0 complete runs, no discount: 6 x 65000 = 390000; "
            f"got {six['quoted_total_cents']}"
        )

        seven = create_booking(vessel["id"], renter, headers,
                               start_date="2026-09-08", end_date="2026-09-15")
        assert seven["total_nights"] == 7
        assert seven["quoted_total_cents"] == 409500, (
            "floor(7/7) = 1 run: 455000 - 45500 = 409500; "
            f"got {seven['quoted_total_cents']}"
        )


class TestParallelDimensionInitialState:
    def test_booking_initial_state_held(self, api):
        """PRD §3.4: "A created booking lands in `HELD` with
        `settlement_status` `NONE`, `deposit_status` `PENDING`, and
        `orientation_status` `NOT_STARTED`; `total_nights` is stored, the quote
        is pinned, and `hold_expires_at` is set to 48 hours after
        `created_at`."
        PRD §2.10: "While the dimension is `PENDING`, `deposit_held_cents` is 0
        — nothing has been captured."

        Design: Corner/state_machines/booking_initial_state_held
        """
        vessel = setup_fleet_with_rate()
        renter, headers, _ = create_qualified_renter(
            full_name="Ini Tial", email="ini@x.com", cert_number="CERT-0010")

        booking = create_booking(vessel["id"], renter, headers,
                                 start_date="2026-08-20", end_date="2026-08-24")
        assert_booking(booking)
        assert booking["status"] == "HELD"
        assert booking["settlement_status"] == "NONE"
        assert booking["deposit_status"] == "PENDING"
        assert booking["orientation_status"] == "NOT_STARTED"
        # COMPACT_36 base deposit 150000 x multiplier 1.0 (risk score 0)
        assert booking["deposit_required_cents"] == 150000
        assert booking["deposit_held_cents"] == 0, (
            "PENDING deposit captures nothing"
        )
        delta = _parse_iso(booking["hold_expires_at"]) - _parse_iso(booking["created_at"])
        assert delta == timedelta(hours=48), (
            f"hold_expires_at must be created_at + 48h, got delta {delta}"
        )

    def test_clock_default_underlies_hold_expiry(self, api):
        """PRD §2.4: "At server startup the clock reads exactly
        `2026-08-01T00:00:00Z`, and before any clock-setting call it continues
        to read that default."
        PRD §3.4: "`hold_expires_at` is set to 48 hours after `created_at`."

        Design: Corner/endpoints/clock_default_underlies_hold_expiry
        """
        vessel = setup_fleet_with_rate()
        renter, headers, _ = create_qualified_renter(
            full_name="Clo Ck", email="clk@x.com", cert_number="CERT-0011")

        booking = create_booking(vessel["id"], renter, headers,
                                 start_date="2026-08-20", end_date="2026-08-24")
        created = _parse_iso(booking["created_at"])
        assert created == datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc), (
            "no clock call has been made, so creation stamps the fixed default "
            f"logical clock, got {booking['created_at']}"
        )
        hold = _parse_iso(booking["hold_expires_at"])
        assert hold == datetime(2026, 8, 3, 0, 0, 0, tzinfo=timezone.utc), (
            f"hold_expires_at must be created_at + 48h, got {booking['hold_expires_at']}"
        )


class TestBookingReadSurface:
    def test_booking_get_not_found_returns_404(self, api):
        """PRD §2.6: "The request is rejected immediately with `ERR_NOT_FOUND`
        (HTTP 404) for the first identifier in the path that does not
        correspond to an existing resource, before any later segment is
        examined."

        Design: Corner/entities/booking_get_not_found_returns_404
        """
        resp = api.get_booking(NON_EXISTENT_UUID, DS)
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
        assert isinstance(error["error_id"], str)
        assert isinstance(error["message"], str) and error["message"].strip()

    def test_list_bookings_filter_and_pagination(self, api):
        """PRD §3.4: "For planning and reconciliation, the booking list view
        accepts optional `vessel_id`, `renter_id` and `status` filters
        alongside pagination; a `Renter` caller only ever sees their own
        bookings there."
        PRD §2.3: "The `limit` parameter caps the number of returned items;
        when omitted it defaults to 10, and it is bounded below by 1 and above
        by 100."

        Design: Corner/entities/list_bookings_filter_and_pagination
        """
        v1 = create_vessel(name="Compact P1", size_class="COMPACT_36",
                           fuel_tank_capacity_gallons=150)
        v2 = create_vessel(name="Compact P2", size_class="COMPACT_36",
                           fuel_tank_capacity_gallons=150)
        create_season_rate(size_class="COMPACT_36", season="PEAK",
                           start_date="2026-06-01", end_date="2026-08-31",
                           nightly_rate_cents=45000, weekly_discount_pct=10)
        renter, headers, _ = create_qualified_renter(
            full_name="Pag Inate", email="pag@x.com", cert_number="CERT-0012")
        for start, end in (("2026-08-10", "2026-08-12"),
                           ("2026-08-12", "2026-08-14"),
                           ("2026-08-14", "2026-08-16")):
            create_booking(v1["id"], renter, headers, start_date=start, end_date=end)
        create_booking(v2["id"], renter, headers,
                       start_date="2026-08-10", end_date="2026-08-12")

        page1, meta1 = validate_paginated(
            api.list_bookings(FM, params={"vessel_id": v1["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3, "filter restricts the count to vessel 1"
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_bookings(FM, params={"vessel_id": v1["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        default_page, default_meta = validate_paginated(
            api.list_bookings(FM, params={"vessel_id": v1["id"]}))
        assert default_meta["limit"] == 10, "omitted limit defaults to 10"
        assert len(default_page) == 3


class TestHalfOpenStayOverlap:
    def test_adjacent_booking_allowed_overlapping_rejected(self, api):
        """PRD §2.9: "Overlap between two bookings is evaluated under half-open
        comparison, which means a back-to-back pair where one booking's
        `end_date` equals the other's `start_date` does **not** conflict —
        adjacency is allowed."
        PRD §3.4: "the half-open stay interval must not intersect any other
        booking of the same vessel in `CONFIRMED`, `CHECKED_OUT`,
        `INTERRUPTED`, or `RETURNED`, with pure adjacency allowed
        (`ERR_VESSEL_DATE_CONFLICT`)"

        Design: Difficulty/resource_temporal_overlap/booking_half_open_adjacency_on_vessel
        """
        vessel = setup_fleet_with_rate(size_class="STANDARD_44", tank=200)
        renter, headers, _ = create_qualified_renter(
            full_name="Hal Fopen", email="hal@x.com", cert_number="CERT-0013")
        g = create_booking(vessel["id"], renter, headers,
                           start_date="2026-08-10", end_date="2026-08-17")
        g = validate_success(api.confirm_booking(g["id"], headers), 200)
        assert g["status"] == "CONFIRMED"

        adjacent = api.create_booking(
            {
                "vessel_id": vessel["id"],
                "renter_id": renter["id"],
                "start_date": "2026-08-17",
                "end_date": "2026-08-20",
                "party_size": 2,
            },
            headers,
        )
        h = validate_success(adjacent, 201)
        assert h["status"] == "HELD", "start == prior end_date is pure adjacency"

        overlapping = api.create_booking(
            {
                "vessel_id": vessel["id"],
                "renter_id": renter["id"],
                "start_date": "2026-08-16",
                "end_date": "2026-08-18",
                "party_size": 2,
            },
            headers,
        )
        validate_error(overlapping, ApiErrorId.ERR_VESSEL_DATE_CONFLICT, 409)

    def test_held_bookings_do_not_block_until_confirm(self, api):
        """PRD §3.4: "the half-open stay interval must not intersect any other
        booking of the same vessel in `CONFIRMED`, `CHECKED_OUT`,
        `INTERRUPTED`, or `RETURNED`, with pure adjacency allowed
        (`ERR_VESSEL_DATE_CONFLICT`)"
        PRD §3.5: "the vessel-overlap, maintenance and rate-coverage checks are
        re-evaluated (`ERR_VESSEL_DATE_CONFLICT`,
        `ERR_MAINTENANCE_DATE_CONFLICT`, `ERR_RATE_NOT_CONFIGURED`)"

        Design: Difficulty/resource_temporal_overlap/booking_half_open_adjacency_on_vessel
        """
        vessel = setup_fleet_with_rate(size_class="STANDARD_44", tank=200)
        renter, headers, _ = create_qualified_renter(
            full_name="Hel Dopen", email="held@x.com", cert_number="CERT-0014")

        b1 = create_booking(vessel["id"], renter, headers,
                            start_date="2026-08-10", end_date="2026-08-15")
        # HELD is outside the blocking set, so the overlapping create succeeds.
        b2 = create_booking(vessel["id"], renter, headers,
                            start_date="2026-08-12", end_date="2026-08-17")
        assert b1["status"] == "HELD" and b2["status"] == "HELD"

        b1 = validate_success(api.confirm_booking(b1["id"], headers), 200)
        assert b1["status"] == "CONFIRMED"

        # Confirm re-evaluates the overlap; b1 now blocks b2's nights.
        resp = api.confirm_booking(b2["id"], headers)
        validate_error(resp, ApiErrorId.ERR_VESSEL_DATE_CONFLICT, 409)


class TestCertificateCoverageBoundary:
    def test_certificate_expiry_equals_end_date_allowed(self, api):
        """PRD §2.9: "Certificate coverage has its own inclusive rule: a
        certificate covers a trip if and only if its `expires_on` falls on or
        after the booking's `end_date`, so a certificate expiring exactly on
        the checkout day still covers the trip."
        PRD §3.4: "the renter must be `QUALIFIED` and hold at least one
        `VERIFIED` certificate whose `expires_on` reaches the booking's
        `end_date` (`ERR_RENTER_NOT_QUALIFIED`)"

        Design: Difficulty/boundary_precision_check/certificate_expiry_equals_end_date_allowed
        """
        vessel = setup_fleet_with_rate()
        r1, h1 = register_renter(full_name="Ed Geday", email="ed@x.com",
                                 date_of_birth="1992-04-04")
        c1 = submit_certificate(r1, h1, cert_number="C-801",
                                issued_on="2025-08-24", expires_on="2026-08-24")
        verify_certificate(c1["id"])
        r2, h2 = register_renter(full_name="Ed Daybefore", email="ed2@x.com",
                                 date_of_birth="1992-04-05")
        c2 = submit_certificate(r2, h2, cert_number="C-802",
                                issued_on="2025-08-23", expires_on="2026-08-23")
        verify_certificate(c2["id"])

        ok = api.create_booking(
            {
                "vessel_id": vessel["id"],
                "renter_id": r1["id"],
                "start_date": "2026-08-20",
                "end_date": "2026-08-24",
                "party_size": 2,
            },
            h1,
        )
        booking = validate_success(ok, 201)
        assert booking["status"] == "HELD", (
            "expires_on == end_date satisfies the inclusive coverage rule"
        )

        resp = api.create_booking(
            {
                "vessel_id": vessel["id"],
                "renter_id": r2["id"],
                "start_date": "2026-08-20",
                "end_date": "2026-08-24",
                "party_size": 2,
            },
            h2,
        )
        validate_error(resp, ApiErrorId.ERR_RENTER_NOT_QUALIFIED, 422)

    def test_certificate_expiry_boundary_holds_at_confirm(self, api):
        """PRD §3.5: "the renter must still be `QUALIFIED` with a `VERIFIED`
        certificate covering `end_date` (`ERR_RENTER_NOT_QUALIFIED`)"
        PRD §2.9: "a certificate covers a trip if and only if its `expires_on`
        falls on or after the booking's `end_date`, so a certificate expiring
        exactly on the checkout day still covers the trip."

        Design: Difficulty/boundary_precision_check/certificate_expiry_equals_end_date_allowed
        """
        vessel = setup_fleet_with_rate()
        r1, h1 = register_renter(full_name="Con Firm", email="conf@x.com",
                                 date_of_birth="1992-05-05")
        c1 = submit_certificate(r1, h1, cert_number="C-803",
                                issued_on="2025-08-24", expires_on="2026-08-24")
        verify_certificate(c1["id"])

        booking = create_booking(vessel["id"], r1, h1,
                                 start_date="2026-08-20", end_date="2026-08-24")
        confirmed = validate_success(api.confirm_booking(booking["id"], h1), 200)
        assert confirmed["status"] == "CONFIRMED", (
            "the inclusive coverage rule is re-evaluated at confirm and passes "
            "for expires_on == end_date"
        )
