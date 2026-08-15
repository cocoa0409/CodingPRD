"""Seller staffing, session creation rules, and show-floor selling."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_allocation,
    assert_sale_record,
    create_active_tour,
    create_seller,
    create_seller_session,
    create_seller_session_payload,
    create_show,
    create_show_payload,
    create_tour,
    generate_allocations_payload,
    get_allocation,
    get_session,
    get_success_data,
    make_seller_headers,
    open_show,
    record_sale,
    setup_selling_show,
    staff_session,
    validate_error,
    validate_paginated,
)

TM1 = TEST_USERS["tour_manager_headers"]
ACCT1 = TEST_USERS["accountant_headers"]


def test_seller_cannot_create_show(api):
    """PRD §2.1: "A caller whose authenticated role is not in an endpoint's
    authorized role list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | /merch/shows | Create a show; venue-date uniqueness and
    commission config validated; starts `SCHEDULED` | TourManager |"

    Design: Corner/rbac/seller_cannot_create_show
    """
    tour = create_tour(name="RB1 Tour")
    seller = create_seller(tour["id"], display_name="Seller A", seller_code="RB1-A")

    resp = api.create_show(
        create_show_payload(tour["id"], city="Laramie", venue_name="RB1 Hall",
                            show_date="2026-09-17T20:00:00Z"),
        make_seller_headers(seller["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    _rows, meta = validate_paginated(
        api.list_shows(TM1, params={"tour_id": tour["id"]}))
    assert meta["total_count"] == 0, "no Show row may be created"


def test_seller_double_booked_same_date(api):
    """PRD §3.4: "The show must be `OPEN` (otherwise `ERR_INVALID_SHOW_STATE`),
    the seller must belong to the show's tour (otherwise
    `ERR_CROSS_TOUR_REFERENCE`), the seller must not already hold another
    non-`CANCELLED` session on any show whose `show_date` falls on the same
    calendar date (otherwise `ERR_SELLER_DOUBLE_BOOKED`), and at most one
    session may exist per show-and-seller pair (otherwise
    `ERR_SESSION_EXISTS`)."

    Design: Corner/validations/seller_double_booked_same_date
    """
    tour = create_active_tour(name="VA1 Tour")
    h1 = create_show(tour["id"], city="Fargo", venue_name="VA1 One",
                     show_date="2026-09-07T20:00:00Z")
    h2 = create_show(tour["id"], city="Fargo", venue_name="VA1 Two",
                     show_date="2026-09-07T13:00:00Z")
    seller = create_seller(tour["id"], display_name="Seller A", seller_code="VA1-A")
    open_show(h1["id"])
    open_show(h2["id"])
    create_seller_session(h1["id"], seller["id"])

    resp = api.create_seller_session(
        create_seller_session_payload(h2["id"], seller["id"], 3000), TM1)
    validate_error(resp, ApiErrorId.ERR_SELLER_DOUBLE_BOOKED)

    rows, meta = validate_paginated(
        api.list_seller_sessions(TM1, params={"seller_id": seller["id"]}))
    assert meta["total_count"] == 1, "no second session row may be created"


class TestCrossTourSessionBeatsDoubleBooking:
    def _setup_two_tours_same_date(self, api):
        """Tour 1 with OPEN show H1 (2026-08-21) and seller A holding a session;
        tour 2 with OPEN show H2 on the same calendar date."""
        t1 = create_active_tour(name="PP2 Tour One")
        t2 = create_active_tour(name="PP2 Tour Two")
        h1 = create_show(t1["id"], city="Gary", venue_name="PP2 One",
                         show_date="2026-08-21T20:00:00Z")
        h2 = create_show(t2["id"], city="Gary", venue_name="PP2 Two",
                         show_date="2026-08-21T19:00:00Z")
        seller = create_seller(t1["id"], display_name="Seller A",
                               seller_code="PP2-A")
        open_show(h1["id"])
        open_show(h2["id"])
        create_seller_session(h1["id"], seller["id"])
        return t1, t2, h1, h2, seller

    def test_referential_error_wins(self, api):
        """PRD §2.7: "When several checks could fail on the same request,
        exactly one error is reported: the checks below run in the order listed,
        and the earliest failing check wins."
        PRD §2.7: "6. Cross-tour referential coherence —
        `ERR_CROSS_TOUR_REFERENCE` (HTTP 422)."
        PRD §2.7: "9. Seller double-booking — `ERR_SELLER_DOUBLE_BOOKED`
        (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/session_cross_tour_seller_beats_double_booking
        """
        _t1, _t2, _h1, h2, seller = self._setup_two_tours_same_date(api)

        resp = api.create_seller_session(
            create_seller_session_payload(h2["id"], seller["id"], 3000), TM1)
        validate_error(resp, ApiErrorId.ERR_CROSS_TOUR_REFERENCE)

    def test_rejected_cross_tour_session_creates_no_row(self, api):
        """PRD §2.7: "When several checks could fail on the same request,
        exactly one error is reported: the checks below run in the order listed,
        and the earliest failing check wins."
        PRD §2.7: "6. Cross-tour referential coherence —
        `ERR_CROSS_TOUR_REFERENCE` (HTTP 422)."
        PRD §3.4: "The show must be `OPEN` (otherwise
        `ERR_INVALID_SHOW_STATE`), the seller must belong to the show's tour
        (otherwise `ERR_CROSS_TOUR_REFERENCE`), the seller must not already hold
        another non-`CANCELLED` session on any show whose `show_date` falls on
        the same calendar date (otherwise `ERR_SELLER_DOUBLE_BOOKED`), and at
        most one session may exist per show-and-seller pair (otherwise
        `ERR_SESSION_EXISTS`)."

        Design: Difficulty/priority_pair_validation_conflict/session_cross_tour_seller_beats_double_booking
        """
        _t1, _t2, _h1, h2, seller = self._setup_two_tours_same_date(api)

        resp = api.create_seller_session(
            create_seller_session_payload(h2["id"], seller["id"], 3000), TM1)
        validate_error(resp, ApiErrorId.ERR_CROSS_TOUR_REFERENCE)

        _rows_h2, meta_h2 = validate_paginated(
            api.list_seller_sessions(TM1, params={"show_id": h2["id"]}))
        assert meta_h2["total_count"] == 0, "no session row on the other tour's show"
        _rows_s, meta_s = validate_paginated(
            api.list_seller_sessions(TM1, params={"seller_id": seller["id"]}))
        assert meta_s["total_count"] == 1


def test_duplicate_session_show_product_and_allocation_rejected(api):
    """PRD §3.4: "The show must be `OPEN` (otherwise `ERR_INVALID_SHOW_STATE`),
    the seller must belong to the show's tour (otherwise
    `ERR_CROSS_TOUR_REFERENCE`), the seller must not already hold another
    non-`CANCELLED` session on any show whose `show_date` falls on the same
    calendar date (otherwise `ERR_SELLER_DOUBLE_BOOKED`), and at most one
    session may exist per show-and-seller pair (otherwise `ERR_SESSION_EXISTS`)."
    PRD §3.2: "Only one price row may exist per show-and-product pair (a
    duplicate fails with `ERR_SHOW_PRODUCT_EXISTS`), and the row can be created
    only while the show is `SCHEDULED`."
    PRD §3.3: "Generation is allowed only once per show-and-product pair; a
    second run is rejected with `ERR_ALLOCATIONS_EXIST`, and attempting it on a
    show no longer `SCHEDULED` fails with `ERR_INVALID_SHOW_STATE`."

    Design: Corner/validations/duplicate_session_show_product_and_allocation_rejected
    """
    # PRD §2.7 runs state preconditions (check 4) before uniqueness (check
    # 11), so the price-row and allocation duplicates must be attempted while
    # the show is still SCHEDULED; the session duplicate requires an OPEN show.
    world = setup_selling_show(tour_name="VA10 Tour", city="Bozeman",
                               venue_name="VA10 Hall",
                               show_date="2026-09-13T20:00:00Z",
                               total_units=100, num_sellers=1, open=False)
    seller = world["sellers"][0]

    resp2 = api.create_show_product(
        {"show_id": world["show"]["id"], "product_id": world["product"]["id"],
         "price_cents": 4500},
        TM1)
    validate_error(resp2, ApiErrorId.ERR_SHOW_PRODUCT_EXISTS)

    resp3 = api.generate_allocations(
        world["show"]["id"],
        generate_allocations_payload(world["product"]["id"], 50),
        TM1)
    validate_error(resp3, ApiErrorId.ERR_ALLOCATIONS_EXIST)

    open_show(world["show"]["id"])
    create_seller_session(world["show"]["id"], seller["id"])

    resp1 = api.create_seller_session(
        create_seller_session_payload(world["show"]["id"], seller["id"], 7000),
        TM1)
    validate_error(resp1, ApiErrorId.ERR_SESSION_EXISTS)


def test_oversale_beyond_on_hand_rejected(api):
    """PRD §3.4: "The session must be `OPEN` (otherwise `ERR_SESSION_NOT_OPEN`),
    the caller must be the session's owning seller (otherwise
    `ERR_NOT_RESOURCE_OWNER`), the allocation must belong to the session's show
    (otherwise `ERR_CROSS_TOUR_REFERENCE`), a show product price row must exist
    for that show and product (otherwise `ERR_PRICE_NOT_SET`), and the quantity
    must fit within the allocation's `quantity_on_hand` (otherwise
    `ERR_INSUFFICIENT_ALLOCATION`)."
    PRD §3.3: "Each allocation also tracks `quantity_sold` (the sum of
    quantities over that allocation's `ACTIVE` sale records),
    `quantity_returned`, `quantity_liquidated`, and `quantity_shrunk` (all zero
    until close-out), and exposes `quantity_on_hand` — the allocated units minus
    everything sold, returned, liquidated, or shrunk."

    Design: Corner/validations/oversale_beyond_on_hand_rejected
    """
    world = setup_selling_show(tour_name="VA2 Tour", city="Minot",
                               venue_name="VA2 Hall",
                               show_date="2026-09-08T20:00:00Z",
                               total_units=10, num_sellers=1)
    seller = world["sellers"][0]
    session = staff_session(world, count_out=False)

    resp = api.create_sale_record(
        {"session_id": session["id"],
         "allocation_id": world["allocation"]["id"],
         "quantity": 11, "tender": "CASH"},
        make_seller_headers(seller["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ALLOCATION)

    sale = record_sale(session["id"], world["allocation"]["id"], 10, "CASH",
                       seller["id"])
    assert_sale_record(sale)
    allocation = get_allocation(world["allocation"]["id"])
    assert allocation["quantity_sold"] == 10
    assert allocation["quantity_on_hand"] == 0, "exactly-on-hand sale is allowed"


class TestSaleOnCountedOutSessionBeatsOversell:
    def _counted_out_world(self, api):
        world = setup_selling_show(tour_name="PP1 Tour", city="Akron",
                                   venue_name="PP1 Hall",
                                   show_date="2026-08-20T20:00:00Z",
                                   total_units=100, num_sellers=1)
        session = staff_session(world, counted_cash_cents=5000)
        assert session["status"] == "COUNTED_OUT"
        return world

    def test_state_error_reported_not_oversell(self, api):
        """PRD §2.7: "When several checks could fail on the same request,
        exactly one error is reported: the checks below run in the order listed,
        and the earliest failing check wins."
        PRD §2.7: "4. State preconditions, including cross-entity state gates
        (an `ACTIVE` tour to open a show, sessions verified to reconcile, and so
        on) — the state errors `ERR_INVALID_TOUR_STATE`, `ERR_TOUR_NOT_ACTIVE`,
        `ERR_INVALID_SHOW_STATE`, `ERR_SESSION_NOT_OPEN`,
        `ERR_SESSION_NOT_COUNTED_OUT`, `ERR_UNRESOLVED_SESSIONS`,
        `ERR_SETTLEMENT_NOT_RECONCILED`, `ERR_INVALID_SETTLEMENT_STATE`,
        `ERR_SHIPMENT_NOT_DRAFT`, `ERR_SHIPMENT_NOT_DISPATCHED`,
        `ERR_ORDER_NOT_PLACED`, `ERR_ALREADY_TERMINAL`, or
        `ERR_SHOWS_NOT_TERMINAL` (all HTTP 409)."
        PRD §2.7: "15. Quantity and stock sufficiency —
        `ERR_INSUFFICIENT_ALLOCATION` or `ERR_INSUFFICIENT_STOCK` (both
        HTTP 409)."
        PRD §3.4: "The session must be `OPEN` (otherwise
        `ERR_SESSION_NOT_OPEN`)"

        Design: Difficulty/priority_pair_validation_conflict/sale_on_counted_out_session_state_beats_oversell
        """
        world = self._counted_out_world(api)
        seller = world["sellers"][0]

        resp = api.create_sale_record(
            {"session_id": world["sessions"][0]["id"],
             "allocation_id": world["allocation"]["id"],
             "quantity": 999, "tender": "CASH"},
            make_seller_headers(seller["id"]))
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_OPEN)

    def test_rejected_sale_leaves_no_partial_effect(self, api):
        """PRD §2.7: "When several checks could fail on the same request,
        exactly one error is reported: the checks below run in the order listed,
        and the earliest failing check wins."
        PRD §3.3: "Each allocation also tracks `quantity_sold` (the sum of
        quantities over that allocation's `ACTIVE` sale records),
        `quantity_returned`, `quantity_liquidated`, and `quantity_shrunk` (all
        zero until close-out), and exposes `quantity_on_hand` — the allocated
        units minus everything sold, returned, liquidated, or shrunk."

        Design: Difficulty/priority_pair_validation_conflict/sale_on_counted_out_session_state_beats_oversell
        """
        world = self._counted_out_world(api)
        seller = world["sellers"][0]

        resp = api.create_sale_record(
            {"session_id": world["sessions"][0]["id"],
             "allocation_id": world["allocation"]["id"],
             "quantity": 999, "tender": "CASH"},
            make_seller_headers(seller["id"]))
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_OPEN)

        allocation = get_allocation(world["allocation"]["id"])
        assert allocation["quantity_sold"] == 0, "no partial effect"
        assert allocation["quantity_on_hand"] == 100
        assert get_session(world["sessions"][0]["id"])["status"] == "COUNTED_OUT"


def test_allocation_on_hand_computed_after_sale(api):
    """PRD §3.3: "Each allocation also tracks `quantity_sold` (the sum of
    quantities over that allocation's `ACTIVE` sale records),
    `quantity_returned`, `quantity_liquidated`, and `quantity_shrunk` (all zero
    until close-out), and exposes `quantity_on_hand` — the allocated units minus
    everything sold, returned, liquidated, or shrunk."
    PRD §3.4: "The drawer's expected contents are always derivable: a session's
    `expected_cash_cents` is its `cash_float_cents` plus the sum of
    `gross_cents` over the session's `ACTIVE` sale records tendered `CASH` —
    card sales never enter the drawer, and voided records drop out of the
    expectation."

    Design: Corner/entities/allocation_on_hand_computed_after_sale
    """
    world = setup_selling_show(tour_name="CD4 Tour", city="Aspen",
                               venue_name="CD4 Hall",
                               show_date="2026-08-28T20:00:00Z",
                               total_units=100, num_sellers=1)
    seller = world["sellers"][0]
    session = staff_session(world, count_out=False)
    record_sale(session["id"], world["allocation"]["id"], 10, "CARD",
                seller["id"])

    allocation = get_allocation(world["allocation"]["id"])
    assert_allocation(allocation)
    assert allocation["quantity_allocated"] == 100
    assert allocation["quantity_sold"] == 10
    assert allocation["quantity_on_hand"] == 90

    assert get_session(session["id"])["expected_cash_cents"] == 5000, (
        "a CARD sale never enters the cash drawer")


def test_card_sales_excluded_from_expected_cash(api):
    """PRD §3.4: "The drawer's expected contents are always derivable: a
    session's `expected_cash_cents` is its `cash_float_cents` plus the sum of
    `gross_cents` over the session's `ACTIVE` sale records tendered `CASH` —
    card sales never enter the drawer, and voided records drop out of the
    expectation."

    Design: Corner/calculations/card_sales_excluded_from_expected_cash
    """
    world = setup_selling_show(tour_name="CA3 Tour", city="Blythe",
                               venue_name="CA3 Hall",
                               show_date="2026-09-05T20:00:00Z",
                               total_units=100, num_sellers=1)
    seller = world["sellers"][0]
    session = staff_session(world, count_out=False)
    sale = record_sale(session["id"], world["allocation"]["id"], 5, "CARD",
                       seller["id"])
    assert sale["gross_cents"] == 20000

    session = get_session(session["id"])
    assert session["expected_cash_cents"] == 5000, (
        "expected cash stays at the float: CARD sales are excluded")
    assert get_allocation(world["allocation"]["id"])["quantity_sold"] == 5, (
        "the sale still counts against inventory")


def test_writes_visible_immediately(api):
    """PRD §3.1: "Products can be listed with a `tour_id` filter, and reading
    one product reports the computed `warehouse_stock_by_size`."
    PRD §3.4: "A new session starts `OPEN`; sessions can be listed filtered by
    `show_id` or `seller_id`, and reading one reports the computed
    `expected_cash_cents` and current `cash_variance_cents`."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/writes_visible_immediately
    """
    world = setup_selling_show(
        tour_name="CM1 Tour", city="Vernal", venue_name="CM1 Hall",
        show_date="2026-09-23T20:00:00Z", total_units=100, num_sellers=1,
        product_overrides={"sku": "CM1-TEE", "name": "Tee",
                           "initial_stock_by_size": {"OS": 500}})
    seller = world["sellers"][0]
    session = staff_session(world, count_out=False)

    product_read = get_success_data(api.get_product(world["product"]["id"], TM1))
    assert product_read["warehouse_stock_by_size"]["OS"] == 500

    sale = record_sale(session["id"], world["allocation"]["id"], 3, "CASH",
                       seller["id"])
    assert sale["gross_cents"] == 12000, "the create response is already final"

    session_read = get_success_data(
        api.get_seller_session(session["id"], make_seller_headers(seller["id"])))
    assert session_read["expected_cash_cents"] == 17000, (
        "the very next read reflects the sale: 5000 float + 12000 cash")


def test_accountant_cannot_count_out(api):
    """PRD §2.1: "A caller whose authenticated role is not in an endpoint's
    authorized role list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | /merch/seller-sessions/{id}/count-out | Transition the
    session `OPEN` → `COUNTED_OUT` by the owning seller; records the counted
    drawer and computes variance | Seller |"

    Design: Corner/rbac/accountant_cannot_count_out
    """
    world = setup_selling_show(tour_name="RB2 Tour", city="Cheyenne",
                               venue_name="RB2 Hall",
                               show_date="2026-09-18T20:00:00Z", num_sellers=1)
    session = create_seller_session(world["show"]["id"], world["sellers"][0]["id"])

    resp = api.count_out_session(session["id"], {"counted_cash_cents": 5000},
                                 ACCT1)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_session(session["id"])["status"] == "OPEN"
