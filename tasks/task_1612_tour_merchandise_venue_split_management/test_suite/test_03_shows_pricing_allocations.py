"""Show scheduling, venue calendar capacity, at-show pricing, and the
size-curve allocation split."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_allocation,
    create_active_tour,
    create_product,
    create_show,
    create_show_payload,
    create_show_product,
    create_show_product_payload,
    create_tour,
    generate_allocations,
    get_show,
    get_success_data,
    list_allocations,
    open_show,
    record_sale,
    reprice_payload,
    setup_selling_show,
    staff_session,
    validate_error,
    validate_paginated,
    validate_success,
)

TM1 = TEST_USERS["tour_manager_headers"]


class TestVenueCalendarCapacity:
    def test_same_venue_same_date_conflicts(self, api):
        """PRD §3.2: "The venue's calendar capacity is one show per venue per
        day: no two non-`CANCELLED` shows may share a `venue_name` and the
        calendar-date portion of `show_date`, and a conflicting create is
        rejected with `ERR_VENUE_DATE_CONFLICT` — adjacent dates at the same
        venue are perfectly fine."

        Design: Difficulty/resource_temporal_overlap/venue_same_date_conflict_adjacent_allowed
        """
        tour = create_tour(name="TO1 Tour")
        create_show(tour["id"], city="Vegas", venue_name="Roxy",
                    show_date="2026-08-25T20:00:00Z")

        resp = api.create_show(
            create_show_payload(tour["id"], city="Vegas", venue_name="Roxy",
                                show_date="2026-08-25T12:00:00Z"),
            TM1)
        validate_error(resp, ApiErrorId.ERR_VENUE_DATE_CONFLICT)

    def test_same_venue_adjacent_date_allowed(self, api):
        """PRD §3.2: "The venue's calendar capacity is one show per venue per
        day: no two non-`CANCELLED` shows may share a `venue_name` and the
        calendar-date portion of `show_date`, and a conflicting create is
        rejected with `ERR_VENUE_DATE_CONFLICT` — adjacent dates at the same
        venue are perfectly fine."

        Design: Difficulty/resource_temporal_overlap/venue_same_date_conflict_adjacent_allowed
        """
        tour = create_tour(name="TO1 Tour")
        create_show(tour["id"], city="Vegas", venue_name="Roxy",
                    show_date="2026-08-25T20:00:00Z")

        adjacent = validate_success(
            api.create_show(
                create_show_payload(tour["id"], city="Vegas", venue_name="Roxy",
                                    show_date="2026-08-26T20:00:00Z"),
                TM1),
            201)
        assert adjacent["status"] == "SCHEDULED"


class TestShowOpenGating:
    def test_open_requires_active_tour_rejected(self, api):
        """PRD §3.2: "Opening a show transitions it from `SCHEDULED` to `OPEN`
        and is gated on the parent tour being `ACTIVE` — an attempt against a
        tour still in `PLANNING` fails with `ERR_TOUR_NOT_ACTIVE`, and against a
        show in any other status with `ERR_INVALID_SHOW_STATE`."

        Design: Difficulty/cross_entity_state_dependency/show_open_requires_active_tour
        """
        tour = create_tour(name="CE1 Tour")
        show = create_show(tour["id"], city="Eugene", venue_name="CE1 Hall",
                           show_date="2026-08-23T20:00:00Z")

        resp = api.open_show(show["id"], TM1)
        validate_error(resp, ApiErrorId.ERR_TOUR_NOT_ACTIVE)
        assert get_show(show["id"])["status"] == "SCHEDULED"

    def test_open_succeeds_once_tour_active(self, api):
        """PRD §3.2: "Opening a show transitions it from `SCHEDULED` to `OPEN`
        and is gated on the parent tour being `ACTIVE` — an attempt against a
        tour still in `PLANNING` fails with `ERR_TOUR_NOT_ACTIVE`, and against a
        show in any other status with `ERR_INVALID_SHOW_STATE`."

        Design: Difficulty/cross_entity_state_dependency/show_open_requires_active_tour
        """
        tour = create_tour(name="CE1 Tour")
        show = create_show(tour["id"], city="Eugene", venue_name="CE1 Hall",
                           show_date="2026-08-23T20:00:00Z")
        get_success_data(api.activate_tour(tour["id"], TM1))

        opened = open_show(show["id"])
        assert opened["status"] == "OPEN"


def test_show_reopen_rejected(api):
    """PRD §3.2: "Opening a show transitions it from `SCHEDULED` to `OPEN` and
    is gated on the parent tour being `ACTIVE` — an attempt against a tour still
    in `PLANNING` fails with `ERR_TOUR_NOT_ACTIVE`, and against a show in any
    other status with `ERR_INVALID_SHOW_STATE`."

    Design: Corner/state_machines/show_reopen_rejected
    """
    tour = create_active_tour(name="SM1 Tour")
    show = create_show(tour["id"], city="Lodi", venue_name="SM1 Hall",
                       show_date="2026-08-30T20:00:00Z")
    open_show(show["id"])

    resp = api.open_show(show["id"], TM1)
    validate_error(resp, ApiErrorId.ERR_INVALID_SHOW_STATE)
    assert get_show(show["id"])["status"] == "OPEN"


def test_show_cancel_after_open_rejected(api):
    """PRD §3.2: "Cancelling is a pre-doors operation only: `SCHEDULED` to
    `CANCELLED`, and a show that has already opened can no longer be cancelled,
    failing with `ERR_INVALID_SHOW_STATE`."

    Design: Corner/state_machines/show_cancel_after_open_rejected
    """
    tour = create_active_tour(name="SM2 Tour")
    show = create_show(tour["id"], city="Lodi", venue_name="SM2 Hall",
                       show_date="2026-08-30T20:00:00Z")
    open_show(show["id"])

    resp = api.cancel_show(show["id"], TM1)
    validate_error(resp, ApiErrorId.ERR_INVALID_SHOW_STATE)
    assert get_show(show["id"])["status"] == "OPEN"


def test_show_create_rejects_malformed_commission_tiers(api):
    """PRD §3.2: "A `TIERED` show instead requires `commission_tiers`, a list of
    bracket objects each carrying `up_to_cents` and `rate_bps`, ordered
    ascending by `up_to_cents`, with exactly one trailing bracket whose
    `up_to_cents` is null to catch everything above the last numbered cap; a
    `TIERED` show leaves `flat_commission_bps` null. A flat show missing its
    rate, or a tiered show with missing, unsorted, or improperly terminated
    brackets, is rejected with `ERR_INVALID_COMMISSION_CONFIG`."

    Design: Corner/entities/show_create_rejects_malformed_commission_tiers
    """
    tour = create_tour(name="CD5 Tour")

    resp = api.create_show(
        {
            "tour_id": tour["id"],
            "city": "Moab",
            "venue_name": "CD5 Hall",
            "show_date": "2026-08-29T20:00:00Z",
            "commission_mode": "TIERED",
            # no trailing null-capped bracket: improperly terminated
            "commission_tiers": [{"up_to_cents": 500000, "rate_bps": 1000}],
        },
        TM1)
    validate_error(resp, ApiErrorId.ERR_INVALID_COMMISSION_CONFIG)

    _rows, meta = validate_paginated(
        api.list_shows(TM1, params={"tour_id": tour["id"]}))
    assert meta["total_count"] == 0, "no Show row may be created"


def test_bundle_priced_for_show_rejected(api):
    """PRD §3.2: "The product must be `REGULAR` and belong to the show's tour —
    a cross-tour pairing is rejected with `ERR_CROSS_TOUR_REFERENCE`, and
    attempting to price a `BUNDLE` for at-show sale is rejected with
    `ERR_PRODUCT_NOT_SELLABLE_AT_SHOW`, since bundles are online-only."

    Design: Corner/validations/bundle_priced_for_show_rejected
    """
    tour = create_tour(name="VA9 Tour")
    show = create_show(tour["id"], city="Pierre", venue_name="VA9 Hall",
                       show_date="2026-09-12T20:00:00Z")
    poster = create_product(tour["id"], sku="VA9-POSTER", name="Poster",
                            base_price_cents=2000, initial_stock_by_size={"OS": 100})
    sticker = create_product(tour["id"], sku="VA9-STICKER", name="Sticker",
                             base_price_cents=500, initial_stock_by_size={"OS": 500})
    bundle = create_product(
        tour["id"], sku="VA9-BUNDLE", name="Fan Pack", product_type="BUNDLE",
        base_price_cents=6000,
        bundle_components=[
            {"component_product_id": poster["id"], "qty_per_bundle": 1},
            {"component_product_id": sticker["id"], "qty_per_bundle": 2},
        ],
        initial_stock_by_size={})

    resp = api.create_show_product(
        create_show_product_payload(show["id"], bundle["id"], 6000), TM1)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_SELLABLE_AT_SHOW)

    _rows, meta = validate_paginated(
        api.list_show_products(TM1, params={"show_id": show["id"]}))
    assert meta["total_count"] == 0, "no ShowProduct row may be created"


def test_occ_stale_show_product_version_rejected(api):
    """PRD §3.2: "Repricing remains possible while the show is `SCHEDULED` or
    `OPEN` and is concurrency-guarded: the caller supplies the new `price_cents`
    together with `expected_show_product_version`, and a stale version is
    rejected with `ERR_STALE_VERSION` as described in §2.9."
    PRD §2.4: "`version` is an integer that increments by exactly one on every
    accepted mutation of the resource — activation, closing, and royalty-config
    updates each bump a tour's `version`; a reprice bumps a show product's
    `version`."

    Design: Corner/complexity_layers/occ_stale_show_product_version_rejected
    """
    tour = create_tour(name="CC2 Tour")
    show = create_show(tour["id"], city="Ogden", venue_name="CC2 Hall",
                       show_date="2026-09-21T20:00:00Z")
    product = create_product(tour["id"], sku="CC2-TEE", name="Tee",
                             base_price_cents=4000,
                             initial_stock_by_size={"OS": 100})
    sp = create_show_product(show["id"], product["id"], 4000)
    observed_version = sp["version"]

    first = validate_success(
        api.reprice_show_product(sp["id"], reprice_payload(4200, observed_version),
                                 TM1))
    assert first["price_cents"] == 4200
    assert first["version"] == observed_version + 1, (
        "an accepted reprice increments the version by exactly one")

    resp = api.reprice_show_product(
        sp["id"], reprice_payload(4400, observed_version), TM1)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    reloaded = get_success_data(api.get_show_product(sp["id"], TM1))
    assert reloaded["price_cents"] == 4200, "the losing write is fully rejected"


def test_sale_pins_price_surviving_reprice(api):
    """PRD §3.2: "Later price changes never rewrite history — every sale already
    recorded keeps the unit price pinned onto it at sale time."
    PRD §3.4: "At the moment of recording, the current show product
    `price_cents` is pinned onto the record as `unit_price_cents` — later
    repricing never rewrites it — `gross_cents` is computed as `quantity` times
    `unit_price_cents`, and the record's `show_id` and `product_id` are
    denormalized from the session and allocation for reporting."

    Design: Corner/endpoints/sale_pins_price_surviving_reprice
    """
    world = setup_selling_show(tour_name="EP1 Tour", city="Butte",
                               venue_name="EP1 Hall",
                               show_date="2026-09-14T20:00:00Z",
                               total_units=100, num_sellers=1)
    seller = world["sellers"][0]
    session = staff_session(world, count_out=False)
    first = record_sale(session["id"], world["allocation"]["id"], 2, "CASH",
                        seller["id"])
    assert first["unit_price_cents"] == 4000
    assert first["gross_cents"] == 8000

    sp = world["show_product"]
    repriced = validate_success(
        api.reprice_show_product(sp["id"], reprice_payload(4500, sp["version"]),
                                 TM1))
    assert repriced["price_cents"] == 4500
    assert repriced["version"] == sp["version"] + 1

    second = record_sale(session["id"], world["allocation"]["id"], 2, "CASH",
                         seller["id"])
    assert second["unit_price_cents"] == 4500, "new sales use the new price"
    assert second["gross_cents"] == 9000

    reloaded = get_success_data(api.get_sale_record(first["id"], TM1))
    assert reloaded["unit_price_cents"] == 4000, "history is never rewritten"
    assert reloaded["gross_cents"] == 8000


class TestSizeCurveLargestRemainder:
    def _generate_101_equal_curve(self, api):
        tour = create_tour(name="CF2 Tour")
        show = create_show(tour["id"], city="Boise", venue_name="CF2 Dome",
                           show_date="2026-08-15T20:00:00Z",
                           size_curve={"S": 1, "M": 1, "L": 1, "XL": 1})
        product = create_product(tour["id"], sku="CF2-HOODIE", name="Hoodie",
                                 sized=True, base_price_cents=8000)
        rows = generate_allocations(show["id"], product["id"], 101)
        return tour, show, product, rows

    def test_remainder_tie_broken_by_ascending_size(self, api):
        """PRD §3.3: "For a sized product, let W be the sum of the curve's
        weights. Each size with a positive weight receives a raw share of
        `total_units` multiplied by its weight and divided by W, kept as an
        exact rational; every such size is first floored to a whole unit, and
        the leftover units — the total minus the sum of the floors — are dealt
        out one at a time in order of fractional part, largest first, with ties
        broken in the fixed ascending size order S, then M, then L, then XL,
        then OS."
        PRD §3.3: "One allocation row is created per size with a positive
        weight; sizes with weight zero get no row."

        Design: Difficulty/combinatorial_formula/size_curve_largest_remainder_tie_order
        """
        _tour, _show, _product, rows = self._generate_101_equal_curve(api)
        assert len(rows) == 4, "one row per positive-weight size"
        by_size = {row["size"]: row for row in rows}
        for row in rows:
            assert_allocation(row)
        assert by_size["S"]["quantity_allocated"] == 26, (
            "101 = 25+25+25+25 with one remainder; the tie goes to S")
        assert by_size["M"]["quantity_allocated"] == 25
        assert by_size["L"]["quantity_allocated"] == 25
        assert by_size["XL"]["quantity_allocated"] == 25

    def test_split_conserves_total_units_exactly(self, api):
        """PRD §3.3: "Because the remainder is distributed rather than each size
        rounded independently, the allocated rows always sum exactly to
        `total_units`."
        PRD §3.3: "One allocation row is created per size with a positive
        weight; sizes with weight zero get no row."

        Design: Difficulty/combinatorial_formula/size_curve_largest_remainder_tie_order
        """
        _tour, show, product, rows = self._generate_101_equal_curve(api)
        assert sum(row["quantity_allocated"] for row in rows) == 101, (
            "exact conservation, no rounding loss")
        assert {row["size"] for row in rows} == {"S", "M", "L", "XL"}

        listed = list_allocations({"show_id": show["id"],
                                   "product_id": product["id"]})
        assert len(listed) == 4
        assert sum(row["quantity_allocated"] for row in listed) == 101
