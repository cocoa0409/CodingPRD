"""Cancellation: state gate, refund tiers and boundaries, the weather variant,
OCC on cancel, and the compensating effects on zone occupancy and vessel
nights."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    cancel_booking,
    cancel_booking_payload,
    charge_amounts,
    confirm_booking,
    create_booking,
    create_geo_zone,
    create_qualified_renter,
    create_season_rate,
    create_vessel,
    create_weather_advisory,
    find_charge,
    get_booking,
    itinerary_payload,
    list_charges,
    list_itineraries,
    modify_booking_payload,
    put_itinerary,
    set_clock,
    setup_confirmed_booking,
    setup_returned_booking,
    validate_error,
    validate_success,
    waypoint,
)

FM = TEST_USERS["fleet_manager_headers"]
DS = TEST_USERS["dock_staff_headers"]


class TestCancelStateGate:
    def test_cancel_returned_booking_rejected(self, api):
        """PRD §3.9: "A renter may cancel their own booking while it is `HELD`
        or `CONFIRMED`; from any other state — `CHECKED_OUT`, `INTERRUPTED`,
        `RETURNED`, `CLOSED`, `CANCELLED`, or `EXPIRED` — the attempt is
        `ERR_BOOKING_NOT_CANCELLABLE`."

        Design: Corner/state_machines/cancel_returned_booking_rejected
        """
        ctx = setup_returned_booking(start_date="2026-08-20",
                                     end_date="2026-08-22",
                                     zone_code="ZP-CANCEL")
        booking = ctx["booking"]
        assert booking["status"] == "RETURNED"

        # The OCC version is current; only the closed cancellable set rejects.
        resp = api.cancel_booking(
            booking["id"], cancel_booking_payload(booking["version"]),
            ctx["renter_headers"])
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_CANCELLABLE, 409)

        after = get_booking(booking["id"])
        assert after["status"] == "RETURNED"
        assert charge_amounts(list_charges(booking["id"]),
                              "CANCELLATION_REFUND") == []


class TestRefundTierBoundaries:
    def test_cancel_at_30_days_90_percent(self, api):
        """PRD §3.9: "From `CONFIRMED`, the standard policy tiers the refund
        against the pinned `quoted_total_cents` by the whole days between the
        current date and `start_date`: 30 or more days out refunds 90%; at
        least 14 but fewer than 30 days refunds 50%; at least 8 but fewer than
        14 days refunds 25%; and fewer than 8 days refunds nothing."

        Design: Corner/calculations/cancel_at_30_days_90_percent
        """
        ctx = setup_confirmed_booking(
            size_class="STANDARD_44", tank=200, vessel_name="Standard C30",
            rates=[("PEAK", "2026-06-01", "2026-08-31", 65000, 10),
                   ("SHOULDER", "2026-09-01", "2026-10-31", 47000, 10)],
            start_date="2026-08-31", end_date="2026-09-03",
            renter_name="Tier Thirty", renter_email="t30@x.com")
        booking = ctx["booking"]
        assert booking["quoted_total_cents"] == 159000  # 65000 + 2 x 47000

        # Clock is at the 2026-08-01 default: exactly 30 days before start.
        cancelled = cancel_booking(booking["id"], ctx["renter_headers"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "RENTER_REQUEST"
        assert cancelled["refund_issued_cents"] == 143100, (
            f"30 days out satisfies the >= 30 tier: 159000 x 90% = 143100, got "
            f"{cancelled['refund_issued_cents']}"
        )

    def test_cancel_at_exactly_14_days_gets_50_percent(self, api):
        """PRD §3.9: "at least 14 but fewer than 30 days refunds 50%"
        PRD §3.9: "Whatever the percentage, the refund amount is the pinned
        quote times the percentage divided by 100, rounded half up to whole
        cents."
        PRD §3.9: "When the booking was `CONFIRMED` and the refund is positive,
        a negative `CANCELLATION_REFUND` charge is posted already `REFUNDED`,
        and its amount is added to `refund_issued_cents`."

        Design: Difficulty/boundary_precision_check/cancel_at_exactly_14_days_gets_50_percent
        """
        ctx = setup_confirmed_booking(
            size_class="STANDARD_44", tank=200, vessel_name="Standard Ten",
            start_date="2026-08-15", end_date="2026-08-22",
            renter_name="Bo Undary", renter_email="bo@x.com")
        booking = ctx["booking"]
        assert booking["quoted_total_cents"] == 409500  # 7 x 65000 - 45500
        assert booking["deposit_held_cents"] == 200000

        # Default clock 2026-08-01: exactly 14 days before start.
        cancelled = cancel_booking(booking["id"], ctx["renter_headers"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "RENTER_REQUEST"
        assert cancelled["refund_issued_cents"] == 204750, (
            f"409500 x 50% = 204750, got {cancelled['refund_issued_cents']}"
        )
        assert cancelled["deposit_status"] == "RELEASED"
        assert cancelled["deposit_released_cents"] == 200000
        assert cancelled["deposit_applied_cents"] == 0

        refund_line = find_charge(list_charges(booking["id"]), "CANCELLATION_REFUND")
        assert refund_line["amount_cents"] == -204750
        assert refund_line["status"] == "REFUNDED"

    def test_cancel_at_13_days_gets_25_percent(self, api):
        """PRD §3.9: "at least 14 but fewer than 30 days refunds 50%; at least
        8 but fewer than 14 days refunds 25%"

        Design: Difficulty/boundary_precision_check/cancel_at_exactly_14_days_gets_50_percent
        """
        ctx = setup_confirmed_booking(
            size_class="STANDARD_44", tank=200, vessel_name="Standard Thirteen",
            start_date="2026-08-15", end_date="2026-08-22",
            renter_name="Bo Low", renter_email="bolo@x.com")
        booking = ctx["booking"]
        set_clock("2026-08-02T00:00:00Z")  # 13 days before start

        cancelled = cancel_booking(booking["id"], ctx["renter_headers"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["refund_issued_cents"] == 102375, (
            f"13 days falls in the 8..13 band: 409500 x 25% = 102375, got "
            f"{cancelled['refund_issued_cents']}"
        )

    def test_cancel_at_7_days_zero_refund(self, api):
        """PRD §3.9: "and fewer than 8 days refunds nothing."
        PRD §2.10: "Lines whose computed amount is zero are never posted."
        PRD §3.9: "The deposit dimension moves to `RELEASED` with
        `deposit_released_cents` equal to `deposit_held_cents` and
        `deposit_applied_cents` at 0."

        Design: Corner/calculations/cancel_at_7_days_zero_refund
        """
        ctx = setup_confirmed_booking(
            size_class="COMPACT_36", vessel_name="Compact C7",
            start_date="2026-08-08", end_date="2026-08-10",
            renter_name="Tier Seven", renter_email="t7@x.com")
        booking = ctx["booking"]
        assert booking["quoted_total_cents"] == 90000  # 2 x 45000

        # Default clock 2026-08-01: 7 days before start, below the 8-day tier.
        cancelled = cancel_booking(booking["id"], ctx["renter_headers"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "RENTER_REQUEST"
        assert cancelled["refund_issued_cents"] == 0
        assert cancelled["deposit_status"] == "RELEASED"
        assert cancelled["deposit_released_cents"] == 150000

        charges = list_charges(booking["id"])
        assert [c["line_type"] for c in charges] == ["RENTAL"], (
            "a zero refund posts no CANCELLATION_REFUND line"
        )


class TestWeatherVariant:
    def test_weather_variant_full_refund_on_cancel(self, api):
        """PRD §3.9: "The weather variant overrides the tiers entirely: if any
        `ACTIVE` advisory's window overlaps the stay — its `window_start` falls
        before the booking's `end_date` and its `window_end` after the
        booking's `start_date` — and its `zone_ids` intersect the zones of the
        booking's `APPROVED` itinerary, the refund is a flat 100% regardless of
        timing, and `cancellation_reason` is stamped `WEATHER`."

        Design: Corner/calculations/weather_variant_full_refund_on_cancel
        """
        ctx = setup_confirmed_booking(
            size_class="LUXE_56", tank=300, berth=8, vessel_name="Luxe WxC",
            start_date="2026-08-10", end_date="2026-08-14", party_size=4,
            renter_name="Wx Cancel", renter_email="wxc@x.com",
            with_itinerary=True, zone_code="ZP-CELL",
            itinerary_night="2026-08-10")
        booking = ctx["booking"]
        assert booking["quoted_total_cents"] == 360000  # 4 x 90000
        assert booking["deposit_held_cents"] == 250000

        create_weather_advisory("STORM", [ctx["zone"]["id"]],
                                "2026-08-09T00:00:00Z", "2026-08-15T00:00:00Z")
        set_clock("2026-08-06T00:00:00Z")  # 4 days out: STANDARD tier is 0%

        cancelled = cancel_booking(booking["id"], ctx["renter_headers"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "WEATHER"
        assert cancelled["refund_issued_cents"] == 360000, (
            "the advisory covering the stay window and itinerary zones forces "
            f"the 100% weather variant, got {cancelled['refund_issued_cents']}"
        )
        assert cancelled["deposit_status"] == "RELEASED"
        assert cancelled["deposit_released_cents"] == 250000

        refund_line = find_charge(list_charges(booking["id"]), "CANCELLATION_REFUND")
        assert refund_line["amount_cents"] == -360000
        assert refund_line["status"] == "REFUNDED"


class TestCancelCompensatingEffects:
    def test_zone_occupancy_freed_on_cancellation(self, api):
        """PRD §3.9: "The cleaning turn, if `SCHEDULED` or `IN_PROGRESS`, is
        `CANCELLED`; the orientation, if `IN_PROGRESS`, `COMPLETED`, or
        `COUNTERSIGNED`, is `CANCELLED`; and an `APPROVED` itinerary becomes
        `VOID`, freeing its zone-night occupancy for other renters."
        PRD §3.5: "Occupancy for a zone-night counts `APPROVED` itineraries —
        `SUPERSEDED` and `VOID` records never count — whose bookings sit in
        `CONFIRMED`, `CHECKED_OUT`, `INTERRUPTED`, or `RETURNED` and which
        contain a waypoint on that zone and night."

        Design: Corner/calculations/zone_occupancy_freed_on_cancellation
        """
        v1 = create_vessel(name="Compact ZA", size_class="COMPACT_36",
                           fuel_tank_capacity_gallons=150)
        v2 = create_vessel(name="Compact ZB", size_class="COMPACT_36",
                           fuel_tank_capacity_gallons=150)
        create_season_rate(size_class="COMPACT_36", season="PEAK",
                           start_date="2026-06-01", end_date="2026-08-31",
                           nightly_rate_cents=45000, weekly_discount_pct=10)
        zone = create_geo_zone(zone_code="ZP-FREED", name="Freed Cove",
                               max_vessels_per_night=1,
                               allowed_size_classes=["COMPACT_36"])
        r1, h1, _ = create_qualified_renter(full_name="Jay Occ", email="jay@x.com",
                                            cert_number="C-1318")
        r2, h2, _ = create_qualified_renter(full_name="Kay Occ", email="kay@x.com",
                                            cert_number="C-1319",
                                            issuing_authority="USCG",
                                            cert_issued_on="2026-01-16")
        j = create_booking(v1["id"], r1, h1, start_date="2026-08-20",
                           end_date="2026-08-23")
        j = confirm_booking(j["id"], h1)
        put_itinerary(j["id"], h1, [waypoint(zone["id"], "2026-08-21")])
        k = create_booking(v2["id"], r2, h2, start_date="2026-08-21",
                           end_date="2026-08-24")
        k = confirm_booking(k["id"], h2)

        # J cancels 19 days before start: 135000 x 50% = 67500.
        j = cancel_booking(j["id"], h1)
        assert j["status"] == "CANCELLED"
        assert j["refund_issued_cents"] == 67500
        j_itineraries = list_itineraries(j["id"])
        assert j_itineraries[0]["status"] == "VOID"

        ok = api.put_itinerary(k["id"],
                               itinerary_payload([waypoint(zone["id"], "2026-08-21")]),
                               h2)
        record = validate_success(ok, 201)
        assert record["status"] == "APPROVED", (
            "the VOID itinerary frees the zone-night for other renters"
        )

    def test_cancel_restores_vessel_nights(self, api):
        """PRD §3.4: "the half-open stay interval must not intersect any other
        booking of the same vessel in `CONFIRMED`, `CHECKED_OUT`,
        `INTERRUPTED`, or `RETURNED`, with pure adjacency allowed
        (`ERR_VESSEL_DATE_CONFLICT`)"
        PRD §3.9: "30 or more days out refunds 90%"

        Design: Difficulty/compensating_invariant/vessel_night_partition_survives_create_cancel
        """
        ctx = setup_confirmed_booking(
            size_class="STANDARD_44", tank=200, vessel_name="Standard Sixteen",
            rates=[("SHOULDER", "2026-09-01", "2026-10-31", 47000, 10)],
            start_date="2026-09-01", end_date="2026-09-05",
            renter_name="Nia Nights", renter_email="nia@x.com")
        booking = ctx["booking"]
        assert booking["quoted_total_cents"] == 188000  # 4 x 47000

        cancelled = cancel_booking(booking["id"], ctx["renter_headers"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["refund_issued_cents"] == 169200, (
            f"31 days before start is the 90% tier: 188000 x 90% = 169200, got "
            f"{cancelled['refund_issued_cents']}"
        )

        # CANCELLED is outside the blocking set, so the identical interval is
        # creatable again: the create + cancel pair conserves vessel nights.
        resp = api.create_booking(
            {
                "vessel_id": ctx["vessel"]["id"],
                "renter_id": ctx["renter"]["id"],
                "start_date": "2026-09-01",
                "end_date": "2026-09-05",
                "party_size": 2,
            },
            ctx["renter_headers"],
        )
        recreated = validate_success(resp, 201)
        assert recreated["status"] == "HELD"

    def test_identical_stay_blocked_before_cancel(self, api):
        """PRD §3.4: "the half-open stay interval must not intersect any other
        booking of the same vessel in `CONFIRMED`, `CHECKED_OUT`,
        `INTERRUPTED`, or `RETURNED`, with pure adjacency allowed
        (`ERR_VESSEL_DATE_CONFLICT`)"

        Design: Difficulty/compensating_invariant/vessel_night_partition_survives_create_cancel
        """
        ctx = setup_confirmed_booking(
            size_class="STANDARD_44", tank=200, vessel_name="Standard Seventeen",
            rates=[("SHOULDER", "2026-09-01", "2026-10-31", 47000, 10)],
            start_date="2026-09-01", end_date="2026-09-05",
            renter_name="Nia Twice", renter_email="nia2@x.com")

        # While CONFIRMED, the identical stay conflicts...
        resp = api.create_booking(
            {
                "vessel_id": ctx["vessel"]["id"],
                "renter_id": ctx["renter"]["id"],
                "start_date": "2026-09-01",
                "end_date": "2026-09-05",
                "party_size": 2,
            },
            ctx["renter_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VESSEL_DATE_CONFLICT, 409)

        # ...and after the cancel the nights are restored exactly.
        cancelled = cancel_booking(ctx["booking"]["id"], ctx["renter_headers"])
        assert cancelled["status"] == "CANCELLED"
        resp = api.create_booking(
            {
                "vessel_id": ctx["vessel"]["id"],
                "renter_id": ctx["renter"]["id"],
                "start_date": "2026-09-01",
                "end_date": "2026-09-05",
                "party_size": 2,
            },
            ctx["renter_headers"],
        )
        recreated = validate_success(resp, 201)
        assert recreated["status"] == "HELD"


class TestCancelOptimisticConcurrency:
    def test_occ_cancel_stale_version_returns_412(self, api):
        """PRD §2.8: "Two write operations on the booking aggregate are guarded
        by optimistic concurrency control: date modification and
        renter-initiated cancellation. Each request must carry
        `expected_booking_version`, a non-optional field holding the `version`
        of the booking as the client last observed it. If another writer has
        advanced the booking's version since that observation — for example a
        prior date modification that changed the quote, or a confirm that
        captured funds — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412), preventing the client from acting on a booking state it has
        not observed."

        Design: Corner/cross_cutting_layers/occ_cancel_stale_version_returns_412
        """
        ctx = setup_confirmed_booking(
            size_class="STANDARD_44", tank=200, vessel_name="Standard Occ2",
            rates=[("SHOULDER", "2026-09-01", "2026-10-31", 47000, 10)],
            start_date="2026-09-01", end_date="2026-09-05",
            renter_name="Occ Can", renter_email="occc@x.com")
        booking = ctx["booking"]
        headers = ctx["renter_headers"]
        stale_version = booking["version"]

        modified = validate_success(api.modify_booking(
            booking["id"],
            modify_booking_payload(stale_version, "2026-09-01", "2026-09-06"),
            headers), 200)
        assert modified["quoted_total_cents"] == 235000  # 5 nights x 47000
        adjustment = find_charge(list_charges(booking["id"]), "RENTAL_ADJUSTMENT")
        assert adjustment["amount_cents"] == 47000
        assert adjustment["status"] == "PAID", "positive delta captures funds now"

        # The cancel carries the version observed before the modify.
        resp = api.cancel_booking(booking["id"],
                                  cancel_booking_payload(stale_version), headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        after = get_booking(booking["id"])
        assert after["status"] == "CONFIRMED"
        assert after["refund_issued_cents"] == 0, "no cancellation refund was issued"
