"""Route sale listing lifecycle, transfer gating on open orders, and the
territory valuation window (PRD §3.8, §3.1)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    confirm_order,
    create_distributor,
    create_driver,
    create_order,
    create_product,
    create_trip,
    deliver_order,
    delivered_line,
    make_distributor_owner_headers,
    order_line,
    precool_and_depart,
    set_clock,
    setup_planned_order,
    setup_route_with_store,
    validate_error,
    validate_success,
)

TM = TEST_USERS["territory_manager_headers"]


def test_listing_offer_cycle_withdraw_and_gates(api):
    """PRD §3.8: "The buyer may not be the seller, else `ERR_SELF_DEALING`
    (HTTP 422); the listing must be `LISTED`, else
    `ERR_LISTING_NOT_OPEN_FOR_OFFER`; and the route must still be `ACTIVE`,
    else `ERR_ROUTE_NOT_ACTIVE`."
    PRD §3.8: "both actions require the listing to be `OFFER_PENDING` (else
    `ERR_LISTING_NOT_ACTIONABLE`) and the caller to be the seller (else
    `ERR_OWNERSHIP_MISMATCH`). The seller may also withdraw from `LISTED` or
    `OFFER_PENDING` (else `ERR_LISTING_NOT_ACTIONABLE`), landing the listing
    `WITHDRAWN` with buyer fields cleared."
    PRD §3.8: "approving the transfer requires the listing to be
    `UNDER_CONTRACT` (else `ERR_LISTING_NOT_UNDER_CONTRACT`)"

    Design: Corner/state_machines/listing_offer_cycle_withdraw_and_gates
    """
    refs = setup_route_with_store(prefix="AG")
    d_id = refs["distributor"]["id"]
    d2 = create_distributor(name="Dairy Dist AH", license_number="LIC-AH-1")
    seller = make_distributor_owner_headers(d_id)
    buyer = make_distributor_owner_headers(d2["id"])

    listing = validate_success(
        api.create_route_sale_listing(
            {"route_id": refs["route"]["id"], "asking_price_cents": 5000000}, seller
        ),
        201,
    )
    l1 = listing["id"]
    assert listing["status"] == "DRAFT"
    assert listing["seller_distributor_id"] == d_id

    err1 = api.submit_offer(
        l1, {"buyer_distributor_id": d2["id"], "offer_price_cents": 4900000}, buyer
    )
    validate_error(err1, ApiErrorId.ERR_LISTING_NOT_OPEN_FOR_OFFER)

    err2 = api.approve_transfer(l1, TM)
    validate_error(err2, ApiErrorId.ERR_LISTING_NOT_UNDER_CONTRACT)

    published = validate_success(api.publish_listing(l1, seller), 200)
    assert published["status"] == "LISTED"

    err3 = api.submit_offer(
        l1, {"buyer_distributor_id": d_id, "offer_price_cents": 4900000}, seller
    )
    validate_error(err3, ApiErrorId.ERR_SELF_DEALING)

    offered = validate_success(
        api.submit_offer(
            l1, {"buyer_distributor_id": d2["id"], "offer_price_cents": 4800000}, buyer
        ),
        200,
    )
    assert offered["status"] == "OFFER_PENDING"

    rejected = validate_success(api.reject_offer(l1, seller), 200)
    assert rejected["status"] == "LISTED"
    assert rejected["buyer_distributor_id"] is None, "reject clears buyer fields"

    reoffered = validate_success(
        api.submit_offer(
            l1, {"buyer_distributor_id": d2["id"], "offer_price_cents": 4950000}, buyer
        ),
        200,
    )
    assert reoffered["status"] == "OFFER_PENDING", "a new offer is allowed after the cycle"

    withdrawn = validate_success(api.withdraw_listing(l1, seller), 200)
    assert withdrawn["status"] == "WITHDRAWN"

    err4 = api.publish_listing(l1, seller)
    validate_error(err4, ApiErrorId.ERR_LISTING_NOT_ACTIONABLE)


class TestListingApproveTransferBlockedByOpenOrders:
    def _setup_under_contract(self, api, prefix):
        refs = setup_planned_order(prefix=prefix, quantity_units=10)
        d_id = refs["distributor"]["id"]
        seller = make_distributor_owner_headers(d_id)
        d2 = create_distributor(name=f"Dairy Dist {prefix}-B", license_number=f"LIC-{prefix}-2")
        buyer = make_distributor_owner_headers(d2["id"])
        listing = validate_success(
            api.create_route_sale_listing(
                {"route_id": refs["route"]["id"], "asking_price_cents": 5000000,
                 "trailing_weeks": 12},
                seller,
            ),
            201,
        )
        validate_success(api.publish_listing(listing["id"], seller), 200)
        validate_success(
            api.submit_offer(
                listing["id"],
                {"buyer_distributor_id": d2["id"], "offer_price_cents": 4900000},
                buyer,
            ),
            200,
        )
        contracted = validate_success(api.accept_offer(listing["id"], seller), 200)
        assert contracted["status"] == "UNDER_CONTRACT"
        refs["buyer_id"] = d2["id"]
        refs["listing"] = listing
        return refs

    def test_open_order_blocks_transfer_then_cancel_releases(self, api):
        """PRD §3.8: "approving the transfer requires the listing to be
        `UNDER_CONTRACT` (else `ERR_LISTING_NOT_UNDER_CONTRACT`) and requires
        no order on the route in `PLANNED` or `CONFIRMED` (else
        `ERR_ROUTE_HAS_OPEN_ORDERS`). Approval moves the listing to `CLOSED`
        and rewrites the route's `distributor_id` to the buyer, incrementing
        the route's `version` and refreshing its `updated_at` — territory
        ownership has changed hands."

        Design: Difficulty/cross_entity_state_dependency/listing_approve_transfer_blocked_by_open_orders
        """
        refs = self._setup_under_contract(api, "O")
        l1 = refs["listing"]["id"]

        err = api.approve_transfer(l1, TM)
        validate_error(err, ApiErrorId.ERR_ROUTE_HAS_OPEN_ORDERS)

        owner = make_distributor_owner_headers(refs["distributor"]["id"])
        validate_success(api.cancel_order(refs["order"]["id"], owner), 200)
        closed = validate_success(api.approve_transfer(l1, TM), 200)
        assert closed["status"] == "CLOSED"

        route = validate_success(api.get_route(refs["route"]["id"], TM), 200)
        assert route["distributor_id"] == refs["buyer_id"]
        assert route["version"] > refs["route"]["version"], (
            "transfer increments the route's version"
        )

    def test_open_listing_blocks_route_retire(self, api):
        """PRD §3.1: "Retirement moves an `ACTIVE` or `SUSPENDED` route to
        `RETIRED` — from any other state, `ERR_ROUTE_NOT_ACTIVE` — but only
        when no order on the route stands in `PLANNED` or `CONFIRMED` and no
        sale listing for the route stands in `DRAFT`, `LISTED`,
        `OFFER_PENDING`, or `UNDER_CONTRACT`; either blocker produces
        `ERR_ROUTE_HAS_OPEN_ORDERS`."

        Design: Difficulty/cross_entity_state_dependency/listing_approve_transfer_blocked_by_open_orders
        """
        refs = self._setup_under_contract(api, "O2")
        # Cancel the PLANNED order so the open listing is the sole blocker.
        owner = make_distributor_owner_headers(refs["distributor"]["id"])
        validate_success(api.cancel_order(refs["order"]["id"], owner), 200)
        err = api.retire_route(refs["route"]["id"], TM)
        validate_error(err, ApiErrorId.ERR_ROUTE_HAS_OPEN_ORDERS)


def test_territory_valuation_window_edges(api):
    """PRD §3.8: "The valuation window covers service dates strictly after the
    clock date minus seven times `trailing_weeks` days, up to and including
    the clock date — the lower bound exclusive, the upper bound inclusive."
    PRD §3.8: "The average weekly figure is the window net sales divided by
    `trailing_weeks`, rounded half-up to integer cents, and
    `territory_value_cents` is ten times that average."
    PRD §3.8: "Publishing a `DRAFT` listing moves it to `LISTED` and snapshots
    `territory_value_cents` at that moment."

    Design: Corner/calculations/territory_valuation_window_edges
    """
    set_clock("2026-05-20T00:00:00Z")
    refs = setup_route_with_store(
        prefix="BD", route_overrides={"service_weekdays": ["MON", "WED"]},
    )
    d_id = refs["distributor"]["id"]
    s1 = refs["store"]["id"]
    product = create_product("VAL-1", list_price_cents=250, shelf_life_days=60)
    driver = create_driver(d_id, name="Rex Driver")

    def deliver_on(service_date, units, code_date):
        trip = create_trip(refs["route"]["id"], driver["id"], d_id,
                           service_date=service_date)
        order = create_order(s1, trip["id"], [order_line(product["id"], units)], d_id,
                             delivery_window_start=f"{service_date}T08:00:00Z",
                             delivery_window_end=f"{service_date}T08:30:00Z")
        confirm_order(order["id"], d_id)
        precool_and_depart(trip["id"], driver["id"], service_date)
        set_clock(f"{service_date}T09:00:00Z")
        deliver_order(order["id"], driver["id"],
                      [delivered_line(product["id"], units, code_date)])

    # 2026-05-20 is outside (clock-84d, clock] when clock is 2026-08-14.
    deliver_on("2026-05-20", 4, "2026-06-15")
    deliver_on("2026-08-03", 2, "2026-09-01")
    deliver_on("2026-08-10", 2, "2026-09-01")

    set_clock("2026-08-14T00:00:00Z")
    owner = make_distributor_owner_headers(d_id)
    listing = validate_success(
        api.create_route_sale_listing(
            {"route_id": refs["route"]["id"], "asking_price_cents": 1000000,
             "trailing_weeks": 12},
            owner,
        ),
        201,
    )
    published = validate_success(api.publish_listing(listing["id"], owner), 200)
    assert published["territory_value_cents"] == 830, (
        "window net = 500 + 500 = 1000 (the 2026-05-20 delivery is excluded "
        "by the exclusive lower bound); avg round(1000/12) = 83; 10 x 83 = 830"
    )
