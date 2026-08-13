"""Dynamic nightly pricing, settlement variants, loyalty tiering, and the
demand forecast's two variants."""
import pytest

from test_helpers import (
    ADMIN,
    api_client,
    add_amenity_line,
    assert_booking,
    check_in,
    check_out,
    create_amenity_product,
    create_reserved_booking,
    create_site_with_stalls,
    create_waitlist_entry_payload,
    make_driver_headers,
    register_driver,
    register_drivers,
    set_clock,
    settle_booking,
    validate_paginated,
    validate_success,
)


def _setup_five_stall_site(base=5000):
    ctx = create_site_with_stalls(num_reservable=5, base=base)
    set_clock("2026-08-01T00:00:00Z")
    return ctx


class TestTieredRateAndPeakStacking:

    def test_peak_friday_at_high_occupancy_tier_stacks(self):
        """PRD section 3.2: "The occupancy percentage selects a multiplier
        from the plan: below `tier2_pct` the night takes `mult_low`; from
        `tier2_pct` up to but not including `tier3_pct` it takes `mult_mid`;
        from `tier3_pct` up to but not including `tier4_pct` it takes
        `mult_high`; and at or above `tier4_pct` it takes `mult_max`."
        PRD section 3.2: "when the UTC weekday of the night's arrival date
        falls within the plan's `peak_days` — Friday and Saturday by default —
        the plan's `peak_multiplier` applies; any other weekday takes a factor
        of 1.0. The night's rate is the site's `base_nightly_rate_cents`
        multiplied by the occupancy multiplier and by the peak factor, rounded
        half up to whole cents".

        Design: Difficulty/combinatorial_formula/tiered_rate_peak_and_occupancy_stacking
        """
        ctx = _setup_five_stall_site()
        drivers = register_drivers(5, "CDL-T")
        for d in drivers[:4]:
            create_reserved_booking(d["id"], ctx["site"]["id"],
                                    "2026-08-14", 1)

        fifth = create_reserved_booking(drivers[4]["id"], ctx["site"]["id"],
                                        "2026-08-14", 1)
        assert fifth["quoted_total_cents"] == 7500, (
            f"4/5 = 80% occupancy selects mult_high, Friday stacks the peak "
            f"multiplier: rhu(5000 * 1.25 * 1.2), got "
            f"{fifth['quoted_total_cents']}"
        )

    def test_peak_friday_at_low_and_mid_tiers(self):
        """PRD section 3.2: "Independently, hours-of-service restart demand is
        priced in: when the UTC weekday of the night's arrival date falls
        within the plan's `peak_days` — Friday and Saturday by default — the
        plan's `peak_multiplier` applies; any other weekday takes a factor of
        1.0."
        PRD section 3.2: "Tier boundaries are inclusive on the left — with the
        default plan, occupancy of exactly 60 percent already triggers
        `mult_mid`."

        Design: Difficulty/combinatorial_formula/tiered_rate_peak_and_occupancy_stacking
        """
        ctx = _setup_five_stall_site()
        drivers = register_drivers(5, "CDL-T")
        first = create_reserved_booking(drivers[0]["id"], ctx["site"]["id"],
                                        "2026-08-14", 1)
        assert first["quoted_total_cents"] == 5400, (
            f"0% occupancy mult_low x Friday peak: rhu(5000 * 0.9 * 1.2), "
            f"got {first['quoted_total_cents']}"
        )
        for d in drivers[1:3]:
            create_reserved_booking(d["id"], ctx["site"]["id"],
                                    "2026-08-14", 1)
        fourth = create_reserved_booking(drivers[3]["id"], ctx["site"]["id"],
                                         "2026-08-14", 1)
        assert fourth["quoted_total_cents"] == 6000, (
            f"3/5 = 60% inclusive tier2 boundary selects mult_mid, Friday "
            f"peak stacks: rhu(5000 * 1.0 * 1.2), got "
            f"{fourth['quoted_total_cents']}"
        )


class TestPerNightRounding:

    def test_each_night_rounded_individually(self):
        """PRD section 3.2: "The night's rate is the site's
        `base_nightly_rate_cents` multiplied by the occupancy multiplier and
        by the peak factor, rounded half up to whole cents, and each night is
        rounded individually before any summation."
        PRD section 3.4: "with its `per_night_rates` pinned — a list pairing
        each night's date with its dynamically priced `rate_cents`".

        Design: Difficulty/combinatorial_formula/per_night_rounding_then_sum
        """
        ctx = create_site_with_stalls(num_reservable=3, base=3333)
        driver = register_driver("CDL-R-1", "R One")
        set_clock("2026-08-01T00:00:00Z")

        booking = create_reserved_booking(driver["id"], ctx["site"]["id"],
                                          "2026-08-10", 2)
        rates = booking["per_night_rates"]
        assert [r["date"] for r in rates] == ["2026-08-10", "2026-08-11"]
        assert [r["rate_cents"] for r in rates] == [3000, 3000], (
            "each night rounds half up independently: rhu(3333 * 0.9) = 3000, "
            f"got {rates}"
        )

    def test_quote_sums_per_line_rounded_rates(self):
        """PRD section 2.8: "Each night's dynamic rate is rounded to whole
        cents before any summation".
        PRD section 3.2: "The night's rate is the site's
        `base_nightly_rate_cents` multiplied by the occupancy multiplier and
        by the peak factor, rounded half up to whole cents, and each night is
        rounded individually before any summation."

        Design: Difficulty/combinatorial_formula/per_night_rounding_then_sum
        """
        ctx = create_site_with_stalls(num_reservable=3, base=3333)
        driver = register_driver("CDL-R-1", "R One")
        set_clock("2026-08-01T00:00:00Z")

        booking = create_reserved_booking(driver["id"], ctx["site"]["id"],
                                          "2026-08-10", 2)
        assert booking["quoted_total_cents"] == 6000, (
            f"per-line rounding yields 3000 + 3000 = 6000, not the "
            f"sum-then-round 5999; got {booking['quoted_total_cents']}"
        )


class TestOccupancyTierInclusiveBoundaries:

    def test_tier2_boundary_60_percent_inclusive(self):
        """PRD section 3.2: "Tier boundaries are inclusive on the left — with
        the default plan, occupancy of exactly 60 percent already triggers
        `mult_mid`."
        PRD section 3.2: "The occupancy percentage is one hundred times that
        occupied count divided by the total number of reservable `ACTIVE`
        stalls, and it is compared as an exact ratio — integer or floor
        division before the comparison is forbidden."

        Design: Difficulty/boundary_precision_check/occupancy_tier_inclusive_boundaries_60_and_80
        """
        ctx = _setup_five_stall_site()
        drivers = register_drivers(5, "CDL-B")
        for d in drivers[:2]:
            create_reserved_booking(d["id"], ctx["site"]["id"],
                                    "2026-08-10", 1)
        third = create_reserved_booking(drivers[2]["id"], ctx["site"]["id"],
                                        "2026-08-10", 1)
        assert third["quoted_total_cents"] == 4500, (
            f"2/5 = 40% stays mult_low (Monday, no peak), got "
            f"{third['quoted_total_cents']}"
        )
        fourth = create_reserved_booking(drivers[3]["id"], ctx["site"]["id"],
                                         "2026-08-10", 1)
        assert fourth["quoted_total_cents"] == 5000, (
            f"3/5 = 60% is the inclusive tier2 boundary -> mult_mid 1.0, got "
            f"{fourth['quoted_total_cents']}"
        )

    def test_tier3_boundary_80_percent_inclusive(self):
        """PRD section 3.2: "from `tier3_pct` up to but not including
        `tier4_pct` it takes `mult_high`".
        PRD section 3.2: "Tier boundaries are inclusive on the left — with the
        default plan, occupancy of exactly 60 percent already triggers
        `mult_mid`."

        Design: Difficulty/boundary_precision_check/occupancy_tier_inclusive_boundaries_60_and_80
        """
        ctx = _setup_five_stall_site()
        drivers = register_drivers(5, "CDL-B")
        for d in drivers[:4]:
            create_reserved_booking(d["id"], ctx["site"]["id"],
                                    "2026-08-10", 1)
        fifth = create_reserved_booking(drivers[4]["id"], ctx["site"]["id"],
                                        "2026-08-10", 1)
        assert fifth["quoted_total_cents"] == 6250, (
            f"4/5 = 80% is the inclusive tier3 boundary -> mult_high 1.25 on "
            f"a non-peak Monday: rhu(5000 * 1.25), got "
            f"{fifth['quoted_total_cents']}"
        )


class TestProvisionalQuoteVsFinalSettlement:

    def _setup_booking_with_two_amenity_codes(self):
        """Site (base 5000, 5 reservable stalls) + SHOWER(1500) + WIFI(500) +
        a STANDARD driver whose 1-night Monday booking carries one line each;
        checked in and ready to check out."""
        ctx = _setup_five_stall_site()
        site = ctx["site"]
        shower = create_amenity_product(site["id"], "SHOWER", 1500)
        wifi = create_amenity_product(site["id"], "WIFI", 500)
        driver = register_driver("CDL-DV-1", "Dv One")
        booking = create_reserved_booking(driver["id"], site["id"],
                                          "2026-08-10", 1)
        add_amenity_line(booking["id"], driver["id"], shower["id"], 1)
        add_amenity_line(booking["id"], driver["id"], wifi["id"], 1)
        set_clock("2026-08-10T15:30:00Z")
        check_in(booking["id"], driver["id"])
        set_clock("2026-08-11T10:00:00Z")
        return {"site": site, "driver": driver, "booking": booking}

    def test_quote_and_final_total_diverge_with_amenities(self):
        """PRD section 3.4: "a provisional `quoted_total_cents` equal to the
        parking subtotal minus the loyalty discount at the driver's
        creation-time tier, with no amenity or fee components."
        PRD section 3.5: "Fifth, when the lines in that sum span at least two
        distinct product codes, the bundle discount is 10 percent of the
        amenity subtotal rounded half up — always 0 for `WALK_IN` — and
        `amenity_net_cents` is the subtotal minus it."
        PRD section 3.5: "The provisional quote and the final settlement
        therefore diverge whenever the driver's tier moved, amenity lines
        exist, or fees accrued."

        Design: Difficulty/dual_variant_calc/booking_provisional_quote_vs_final_settlement
        """
        ctx = self._setup_booking_with_two_amenity_codes()
        booking, driver = ctx["booking"], ctx["driver"]
        assert booking["quoted_total_cents"] == 4500, (
            f"provisional quote is parking only: 5000 * 0.9 at 0% occupancy, "
            f"STANDARD tier; got {booking['quoted_total_cents']}"
        )

        settled = check_out(booking["id"], driver["id"])
        assert settled["final_total_cents"] == 6300, (
            f"final = parking 4500 + amenity subtotal 2000 - bundle discount "
            f"200; got {settled['final_total_cents']}"
        )
        assert settled["final_total_cents"] != booking["quoted_total_cents"]

    def test_settlement_component_fields(self):
        """PRD section 3.5: "First, `parking_subtotal_cents` is the sum of the
        pinned `per_night_rates`, each element already rounded when pinned.
        Second, the loyalty percentage is read from the driver's tier at
        settlement time — 15 for `PLATINUM`, 10 for `GOLD`, 5 for `SILVER`, 0
        for `STANDARD`".
        PRD section 3.5: "Fifth, when the lines in that sum span at least two
        distinct product codes, the bundle discount is 10 percent of the
        amenity subtotal rounded half up — always 0 for `WALK_IN` — and
        `amenity_net_cents` is the subtotal minus it. Sixth, `fee_cents`
        carries the overstay penalty for an `OVERSTAY` checkout, the
        cancellation or no-show fee where one applies, and 0 otherwise; fees
        are never discounted. Seventh, `final_total_cents` is the parking net
        plus `amenity_net_cents` plus `fee_cents`."

        Design: Difficulty/dual_variant_calc/booking_provisional_quote_vs_final_settlement
        """
        ctx = self._setup_booking_with_two_amenity_codes()
        settled = check_out(ctx["booking"]["id"], ctx["driver"]["id"])
        assert_booking(settled)
        assert settled["parking_subtotal_cents"] == 4500
        assert settled["discount_cents"] == 0, "STANDARD tier takes 0 percent"
        assert settled["amenity_net_cents"] == 1800, \
            "amenity subtotal 2000 less the 10 percent bundle discount 200"
        assert settled["fee_cents"] == 0
        assert settled["final_total_cents"] == 6300


class TestForecastVariants:

    def _setup_forecast_site(self):
        """5 reservable + 5 first-come stalls; 3 RESERVED bookings and
        2 QUEUED waitlist entries all covering the night of 2026-08-10."""
        ctx = create_site_with_stalls(num_reservable=5, num_first_come=5)
        site = ctx["site"]
        drivers = register_drivers(5, "CDL-F")
        set_clock("2026-08-01T00:00:00Z")
        for d in drivers[:3]:
            create_reserved_booking(d["id"], site["id"], "2026-08-10", 1)
        for d in drivers[3:]:
            resp = api_client.create_waitlist_entry(
                create_waitlist_entry_payload(d["id"], site["id"],
                                              "2026-08-10", 1, "STANDARD"),
                make_driver_headers(d["id"]),
            )
            entry = validate_success(resp, expected_status=201)
            assert entry["status"] == "QUEUED"
        return {"site": site, "drivers": drivers}

    def test_confirmed_variant_counts_only_materialized_bookings(self):
        """PRD section 3.2: "The confirmed variant counts the distinct stalls
        holding a booking in `BOOKED`, `CHECKED_IN`, or `OVERSTAY` whose
        occupancy interval covers the queried night, and reports
        `confirmed_occupied_stalls` together with `confirmed_occupancy_pct`
        (one hundred times that count divided by total stalls, rounded half up
        to two decimal places)."

        Design: Difficulty/dual_variant_calc/forecast_confirmed_only_vs_committed_weighted
        """
        ctx = self._setup_forecast_site()
        resp = api_client.get_site_forecast(ctx["site"]["id"], ADMIN,
                                            params={"date": "2026-08-10"})
        forecast = validate_success(resp)
        assert forecast["confirmed_occupied_stalls"] == 3
        assert forecast["confirmed_occupancy_pct"] == pytest.approx(30.0), (
            f"3 of 10 ACTIVE stalls: got "
            f"{forecast['confirmed_occupancy_pct']}"
        )
        assert forecast["date"] == "2026-08-10", \
            "the response echoes the queried date"

    def test_committed_variant_adds_weighted_waitlist_demand(self):
        """PRD section 3.2: "The committed variant layers waitlist demand on
        top: each `QUEUED` entry whose arrival window covers the night weighs
        one half, each `OFFERED` entry weighs one quarter, and the resulting
        `committed_weighted_demand` — confirmed occupied stalls plus the
        weighted waitlist sum — produces `committed_occupancy_pct` by the same
        rounding."
        PRD section 3.2: "the committed variant, which is strictly greater
        whenever any waitlist demand exists for the night, serves revenue
        forecasting."

        Design: Difficulty/dual_variant_calc/forecast_confirmed_only_vs_committed_weighted
        """
        ctx = self._setup_forecast_site()
        resp = api_client.get_site_forecast(ctx["site"]["id"], ADMIN,
                                            params={"date": "2026-08-10"})
        forecast = validate_success(resp)
        assert forecast["committed_weighted_demand"] == pytest.approx(4.0), (
            f"3 confirmed + 2 x 0.5 QUEUED: got "
            f"{forecast['committed_weighted_demand']}"
        )
        assert forecast["committed_occupancy_pct"] == pytest.approx(40.0)
        assert (forecast["committed_occupancy_pct"]
                > forecast["confirmed_occupancy_pct"])

    def test_forecast_excludes_terminal_bookings(self):
        """PRD section 3.2: "The confirmed variant counts the distinct stalls
        holding a booking in `BOOKED`, `CHECKED_IN`, or `OVERSTAY` whose
        occupancy interval covers the queried night".
        PRD section 3.2: "Entries in `WITHDRAWN`, `EXPIRED`, or `PROMOTED`
        status are excluded, the last because a promoted entry has already
        materialized as a booking and is counted there."

        Design: Corner/calculations/forecast_excludes_terminal_bookings
        """
        ctx = create_site_with_stalls(num_reservable=1, num_first_come=1)
        site = ctx["site"]
        driver = register_driver("CDL-FT-1", "F Tee")
        set_clock("2026-08-01T00:00:00Z")
        booking = create_reserved_booking(driver["id"], site["id"],
                                          "2026-08-10", 1)

        resp = api_client.get_site_forecast(site["id"], ADMIN,
                                            params={"date": "2026-08-10"})
        before = validate_success(resp)
        assert before["confirmed_occupancy_pct"] == pytest.approx(50.0), \
            "1 of 2 ACTIVE stalls"

        resp = api_client.cancel_booking(booking["id"],
                                         make_driver_headers(driver["id"]))
        validate_success(resp, expected_status=200)
        resp = api_client.get_site_forecast(site["id"], ADMIN,
                                            params={"date": "2026-08-10"})
        after = validate_success(resp)
        assert after["confirmed_occupancy_pct"] == pytest.approx(0.0), \
            "a CANCELLED booking drops out of the confirmed variant"
        assert after["committed_occupancy_pct"] == pytest.approx(0.0)


class TestLoyaltyTierBoundary:

    def test_loyalty_tier_twelve_nights_boundary_discount(self):
        """PRD section 3.3: "Tier thresholds are inclusive: at least 12
        settled nights earns `SILVER`, at least 30 earns `GOLD`, and at least
        60 earns `PLATINUM`; below that the driver is `STANDARD`."
        PRD section 3.3: "Separately, the loyalty points ledger credits
        `loyalty_points_balance` with 10 points per booked night each time one
        of the driver's bookings reaches `billing_status` `PAID`, whether the
        driver paid directly or a fleet invoice covering the booking was paid
        in full."
        PRD section 3.5: "paying exactly the remaining balance moves it to
        `PAID`, sets `paid_cents` equal to `final_total_cents`, and credits
        the loyalty ledger with 10 points per `night_count`, recomputing
        `settled_nights_90d` and the tier."

        Design: Corner/calculations/loyalty_tier_twelve_nights_boundary_discount
        """
        ctx = create_site_with_stalls(num_reservable=1)
        site = ctx["site"]
        driver = register_driver("CDL-LT-1", "L Tee")
        set_clock("2026-08-01T00:00:00Z")
        booking = create_reserved_booking(driver["id"], site["id"],
                                          "2026-08-10", 12)
        assert booking["quoted_total_cents"] == 56700, (
            f"9 non-peak nights x 4500 + 3 peak nights (08-14/08-15/08-21) x "
            f"5400, STANDARD tier at creation; got "
            f"{booking['quoted_total_cents']}"
        )
        settled = settle_booking(booking["id"], driver["id"], "2026-08-10",
                                 night_count=12)
        assert settled["final_total_cents"] == 56700, \
            "STANDARD tier at settlement as well: no discount"

        resp = api_client.pay_booking(
            booking["id"], {"amount_cents": 56700},
            make_driver_headers(driver["id"]))
        paid = validate_success(resp, expected_status=201)
        assert paid["billing_status"] == "PAID"

        resp = api_client.get_driver(driver["id"], ADMIN)
        d = validate_success(resp)
        assert d["settled_nights_90d"] == 12
        assert d["loyalty_tier"] == "SILVER", \
            "12 settled nights is the inclusive SILVER threshold"
        assert d["loyalty_points_balance"] == 120, "10 points x 12 nights"

        nxt = create_reserved_booking(driver["id"], site["id"],
                                      "2026-08-25", 1)
        assert nxt["quoted_total_cents"] == 4275, (
            f"SILVER quote: 4500 - rhu(4500 * 5%) = 4275, got "
            f"{nxt['quoted_total_cents']}"
        )
