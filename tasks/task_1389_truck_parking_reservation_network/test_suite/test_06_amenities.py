"""Amenity lines: nightly capacity buckets, inclusive boundaries, and the
pinned unit price."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    add_amenity_line,
    api_client,
    assert_booking_amenity,
    create_amenity_product,
    create_reserved_booking,
    create_site_with_stalls,
    make_driver_headers,
    register_driver,
    register_drivers,
    set_clock,
    settle_booking,
    validate_error,
    validate_success,
)


def _setup_span_bookings(nightly_capacity, night_counts):
    """Site (base 5000) with 3 reservable stalls + a SHOWER product at the
    given capacity + one booking per (driver, spec) pair. night_counts items
    are (arrival_date, night_count) tuples. Clock ends at
    2026-08-01T00:00:00Z."""
    ctx = create_site_with_stalls(num_reservable=3)
    site = ctx["site"]
    product = create_amenity_product(site["id"], "SHOWER", 1500,
                                     nightly_capacity=nightly_capacity)
    set_clock("2026-08-01T00:00:00Z")
    drivers = register_drivers(len(night_counts), "CDL-AM")
    bookings = [
        create_reserved_booking(d["id"], site["id"], arrival, nights)
        for d, (arrival, nights) in zip(drivers, night_counts)
    ]
    return {"site": site, "product": product, "drivers": drivers,
            "bookings": bookings}


class TestNightlyCapacityBoundary:

    def test_consumption_up_to_capacity_allowed(self):
        """PRD section 3.6: "The add is allowed only when consumption plus the
        new `quantity` is at most `nightly_capacity` for every night of the
        span — landing exactly on the capacity is permitted — and any single
        night that would overflow rejects the whole add with
        `ERR_AMENITY_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/shower_nightly_capacity_exactly_at_limit
        """
        ctx = _setup_span_bookings(nightly_capacity=2,
                                   night_counts=[("2026-08-10", 1)] * 3)
        product = ctx["product"]
        line1 = add_amenity_line(ctx["bookings"][0]["id"],
                                 ctx["drivers"][0]["id"], product["id"], 1)
        assert line1["status"] == "RESERVED", "consumed 1 <= capacity 2"
        line2 = add_amenity_line(ctx["bookings"][1]["id"],
                                 ctx["drivers"][1]["id"], product["id"], 1)
        assert_booking_amenity(line2)
        assert line2["status"] == "RESERVED", \
            "landing exactly on the capacity (2 == 2) is permitted"

    def test_one_beyond_capacity_rejected(self):
        """PRD section 3.6: "The add is allowed only when consumption plus the
        new `quantity` is at most `nightly_capacity` for every night of the
        span — landing exactly on the capacity is permitted — and any single
        night that would overflow rejects the whole add with
        `ERR_AMENITY_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/shower_nightly_capacity_exactly_at_limit
        """
        ctx = _setup_span_bookings(nightly_capacity=2,
                                   night_counts=[("2026-08-10", 1)] * 3)
        product = ctx["product"]
        add_amenity_line(ctx["bookings"][0]["id"], ctx["drivers"][0]["id"],
                         product["id"], 1)
        add_amenity_line(ctx["bookings"][1]["id"], ctx["drivers"][1]["id"],
                         product["id"], 1)

        resp = api_client.add_booking_amenity(
            ctx["bookings"][2]["id"],
            {"amenity_product_id": product["id"], "quantity": 1},
            make_driver_headers(ctx["drivers"][2]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AMENITY_CAPACITY_EXCEEDED)


class TestNightlyBucketsNotIntervals:

    def test_second_night_of_span_collides(self):
        """PRD section 3.6: "Capacitated products — those with a non-null
        `nightly_capacity` — are checked night by night across the booking's
        whole span, from `arrival_date` through `night_count` nights. For each
        night, consumption is the total `quantity` across lines in `RESERVED`
        or `FULFILLED` status for the same product whose owning booking's
        night span covers that night, excluding lines whose booking is
        `CANCELLED` or `NO_SHOW`."

        Design: Difficulty/resource_temporal_overlap/shower_nightly_bucket_not_interval
        """
        ctx = _setup_span_bookings(nightly_capacity=1,
                                   night_counts=[("2026-08-10", 2),
                                                 ("2026-08-11", 1),
                                                 ("2026-08-12", 1)])
        product = ctx["product"]
        b1, b2, _ = ctx["bookings"]
        d1, d2, _ = ctx["drivers"]
        add_amenity_line(b1["id"], d1["id"], product["id"], 1)

        # B2's single night (08-11) is B1's second bucket: the 2-night span
        # consumes it even though stall-style interval turnover would call
        # the two stays adjacent.
        resp = api_client.add_booking_amenity(
            b2["id"], {"amenity_product_id": product["id"], "quantity": 1},
            make_driver_headers(d2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AMENITY_CAPACITY_EXCEEDED)

    def test_night_after_span_is_free(self):
        """PRD section 3.6: "Capacitated products — those with a non-null
        `nightly_capacity` — are checked night by night across the booking's
        whole span, from `arrival_date` through `night_count` nights."
        PRD section 3.6: "The add is allowed only when consumption plus the
        new `quantity` is at most `nightly_capacity` for every night of the
        span — landing exactly on the capacity is permitted".

        Design: Difficulty/resource_temporal_overlap/shower_nightly_bucket_not_interval
        """
        ctx = _setup_span_bookings(nightly_capacity=1,
                                   night_counts=[("2026-08-10", 2),
                                                 ("2026-08-11", 1),
                                                 ("2026-08-12", 1)])
        product = ctx["product"]
        b1, _, b3 = ctx["bookings"]
        d1, _, d3 = ctx["drivers"]
        add_amenity_line(b1["id"], d1["id"], product["id"], 1)

        line3 = add_amenity_line(b3["id"], d3["id"], product["id"], 1)
        assert line3["status"] == "RESERVED", (
            "the 08-12 bucket is free: B1's span covers only 08-10 and 08-11"
        )


class TestPinnedUnitPrice:

    def test_amenity_unit_price_pinned_against_later_price_change(self):
        """PRD section 3.6: "Each new line starts `RESERVED` with
        `unit_price_cents` pinned from the product's `price_cents` at add
        time, so later catalog repricing never reaches existing lines."
        PRD section 3.5: "Fourth, the amenity subtotal sums
        `unit_price_cents` times `quantity` times `night_count` over lines in
        `RESERVED` or `FULFILLED` status, excluding `CANCELLED` lines."

        Design: Corner/calculations/amenity_unit_price_pinned_against_later_price_change
        """
        ctx = create_site_with_stalls(num_reservable=1)
        site = ctx["site"]
        product = create_amenity_product(site["id"], "SHOWER", 1500)
        driver = register_driver("CDL-AP-1", "A Pee")
        set_clock("2026-08-01T00:00:00Z")
        booking = create_reserved_booking(driver["id"], site["id"],
                                          "2026-08-10", 1)
        line = add_amenity_line(booking["id"], driver["id"], product["id"], 1)
        assert line["unit_price_cents"] == 1500, "pinned at add time"

        resp = api_client.update_amenity_product(
            site["id"], product["id"], {"price_cents": 2000}, ADMIN)
        validate_success(resp, expected_status=200)

        settled = settle_booking(booking["id"], driver["id"], "2026-08-10", 1)
        assert settled["final_total_cents"] == 6000, (
            f"4500 parking + 1500 pinned amenity (single distinct code, no "
            f"bundle discount); a later reprice must not reach the line; got "
            f"{settled['final_total_cents']}"
        )

        resp = api_client.get_booking_amenity(
            line["id"], make_driver_headers(driver["id"]))
        after = validate_success(resp)
        assert after["unit_price_cents"] == 1500
