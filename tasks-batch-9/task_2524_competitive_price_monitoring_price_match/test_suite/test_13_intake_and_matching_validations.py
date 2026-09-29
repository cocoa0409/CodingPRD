"""Corner-case validation tests for catalog intake and competitor matching.

These tests drive the intake-side refusals to their exact boundaries: the
forward-dated observation instant, the observation proximity window, market
coherence between products, competitors and stores, the two uniqueness keys on
products and matches, and the pagination window on list endpoints.
"""
from test_helpers import (
    ApiErrorId,
    create_change_order_payload,
    create_match_payload,
    create_observation_payload,
    create_product_payload,
    make_data_collector_headers,
    make_platform_admin_headers,
    make_pricing_analyst_headers,
    new_competitor,
    new_market,
    new_match,
    new_observation,
    new_product,
    new_store,
    read_match,
    read_product,
    review_match,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import ANALYST_USER_ID

ADMIN = make_platform_admin_headers()
ANALYST = make_pricing_analyst_headers(ANALYST_USER_ID)
COLLECTOR = make_data_collector_headers()
CLOCK = "2026-08-01T00:00:00Z"


def test_observation_one_second_after_the_clock_is_refused(api):
    """An observed_at one second ahead of the logical clock is refused; the clock instant itself is accepted.

    PRD: "An `observed_at` later than the logical clock's current instant is refused with `ERR_OBSERVATION_IN_FUTURE` (HTTP 422) — the service will not accept a price that has not been seen yet."
    Design: Corner/validations/corner_observation_in_future_rejected_at_one_second
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )
    product = new_product(
        market["id"],
        sku="SKU-FUT-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
    )
    link = new_match(
        product["id"],
        competitor["id"],
        match_method="ATTRIBUTE",
        identifier_score=70,
        attribute_score=70,
        image_score=70,
        competitor_identifier=None,
    )

    refused = api.create_observation(
        create_observation_payload(
            link["id"],
            observed_price_cents=18000,
            collection_method="ONLINE",
            observed_at="2026-08-01T00:00:01Z",
            in_stock=True,
        ),
        COLLECTOR,
    )
    validate_error(refused, ApiErrorId.ERR_OBSERVATION_IN_FUTURE)

    accepted = new_observation(
        link["id"],
        observed_price_cents=18000,
        collection_method="ONLINE",
        observed_at=CLOCK,
        in_stock=True,
    )
    assert accepted["status"] == "ACTIVE"

    # Only the accepted row entered the election.
    elected = read_match(link["id"])
    assert elected["latest_effective_price_cents"] == 18000
    assert elected["gap_bp"] == 11111

    rows, meta = validate_paginated(
        api.list_observations(COLLECTOR, params={"link_id": link["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == accepted["id"]


def test_observation_proximity_is_strict_at_sixty_minutes_per_collection_method(api):
    """Thirty minutes apart on one method is refused, exactly sixty is accepted, and another method never collides.

    PRD: "And to stop a scraper double-posting, no other `ACTIVE` observation on the same match with the same `collection_method` may lie strictly within 60 minutes of the new `observed_at`; a separation of exactly 60 minutes is accepted, while anything closer is refused with `ERR_DUPLICATE_OBSERVATION_WINDOW` (HTTP 409)."
    Design: Corner/validations/corner_duplicate_observation_proximity_window_60_minutes
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )
    product = new_product(
        market["id"],
        sku="SKU-PROX-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="HYBRID",
        tier="PRIMARY",
    )
    link = new_match(
        product["id"],
        competitor["id"],
        match_method="ATTRIBUTE",
        identifier_score=70,
        attribute_score=70,
        image_score=70,
        competitor_identifier=None,
    )
    base = new_observation(
        link["id"],
        observed_price_cents=18000,
        collection_method="ONLINE",
        observed_at="2026-07-31T18:00:00Z",
        in_stock=True,
    )
    assert base["status"] == "ACTIVE"

    too_close = api.create_observation(
        create_observation_payload(
            link["id"],
            observed_price_cents=17900,
            collection_method="ONLINE",
            observed_at="2026-07-31T18:30:00Z",
            in_stock=True,
        ),
        COLLECTOR,
    )
    validate_error(too_close, ApiErrorId.ERR_DUPLICATE_OBSERVATION_WINDOW)

    exactly_sixty = api.create_observation(
        create_observation_payload(
            link["id"],
            observed_price_cents=17800,
            collection_method="ONLINE",
            observed_at="2026-07-31T19:00:00Z",
            in_stock=True,
        ),
        COLLECTOR,
    )
    assert validate_success(exactly_sixty, 201)["status"] == "ACTIVE"

    # A store audit at the very same instant as the online row is a different scope.
    same_instant_other_method = api.create_observation(
        create_observation_payload(
            link["id"],
            observed_price_cents=17700,
            collection_method="STORE_AUDIT",
            observed_at="2026-07-31T18:00:00Z",
            in_stock=True,
        ),
        COLLECTOR,
    )
    assert validate_success(same_instant_other_method, 201)["status"] == "ACTIVE"

    _rows, meta = validate_paginated(
        api.list_observations(
            COLLECTOR, params={"link_id": link["id"], "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 3
    assert read_match(link["id"])["latest_effective_price_cents"] == 17700


def test_cross_market_match_and_cross_market_signage_store_are_refused(api):
    """A product and competitor in different markets, and a signage store outside the product's market, are both incoherent.

    PRD: "Rows that resolve individually may still belong to different markets, and the service refuses those combinations with `ERR_MARKET_MISMATCH` (HTTP 422) in three places: when a proposed match names a product and a competitor whose `market_id` values differ; when a price-match claim's store, product, competitor and policy do not all share one `market_id`; and when a change order's `signage_store_id` names a store outside the product's market."
    Design: Corner/validations/corner_market_mismatch_on_match_and_signage_store
    """
    set_clock(CLOCK)
    west = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )
    east = new_market(
        market_code="US-EAST",
        name="US East",
        strategic_positioning="PREMIUM",
        strategic_index_target_bp=10200,
    )
    product = new_product(
        west["id"],
        sku="SKU-MM-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
    )
    east_competitor = new_competitor(
        east["id"],
        competitor_code="C-EAST",
        name="East Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
    )
    east_store = new_store(
        east["id"],
        store_code="STORE-EAST",
        override_authority_cents=5000,
        label_printer_capacity_per_day=5,
    )

    # Every referenced row exists, so this is a 422 coherence failure, not a 404.
    bad_match = api.create_match(
        create_match_payload(
            product["id"],
            east_competitor["id"],
            match_method="IDENTIFIER",
            identifier_score=95,
            attribute_score=95,
            image_score=95,
            competitor_identifier="00712345678905",
        ),
        ANALYST,
    )
    validate_error(bad_match, ApiErrorId.ERR_MARKET_MISMATCH)

    bad_order = api.create_change_order(
        create_change_order_payload(
            product["id"],
            product["version"],
            origin="MANUAL",
            requested_price_cents=19000,
            effective_from=CLOCK,
            signage_store_id=east_store["id"],
        ),
        ANALYST,
    )
    validate_error(bad_order, ApiErrorId.ERR_MARKET_MISMATCH)

    _matches, match_meta = validate_paginated(
        api.list_matches(ANALYST, params={"product_id": product["id"]})
    )
    assert match_meta["total_count"] == 0
    _orders, order_meta = validate_paginated(
        api.list_change_orders(ANALYST, params={"product_id": product["id"]})
    )
    assert order_meta["total_count"] == 0
    assert read_product(product["id"])["version"] == product["version"]


def test_duplicate_sku_is_absolute_while_a_rejected_match_frees_its_pair(api):
    """A taken sku can never be reused, but a REJECTED match releases its product-and-competitor pair.

    PRD: "The competitor must belong to the same market as the product, or the proposal is refused with `ERR_MARKET_MISMATCH`, and at most one non-rejected match may exist for any one product-and-competitor pair — a second attempt is refused with `ERR_DUPLICATE_RESOURCE`."
    Design: Corner/validations/corner_duplicate_sku_and_duplicate_live_link_pair
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )
    product = new_product(
        market["id"],
        sku="SKU-DUP-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
    )
    competitor = new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
    )
    first_link = new_match(
        product["id"],
        competitor["id"],
        match_method="ATTRIBUTE",
        identifier_score=70,
        attribute_score=70,
        image_score=70,
        competitor_identifier=None,
    )

    # A different category and brand do not rescue a taken (market_id, sku).
    duplicate_sku = api.create_product(
        create_product_payload(
            market["id"],
            sku="SKU-DUP-1",
            category_code="ELECTRONICS",
            brand="Nordis",
            own_price_cents=30000,
            unit_cost_cents=12000,
        ),
        ADMIN,
    )
    validate_error(duplicate_sku, ApiErrorId.ERR_DUPLICATE_RESOURCE)

    duplicate_pair = api.create_match(
        create_match_payload(
            product["id"],
            competitor["id"],
            match_method="ATTRIBUTE",
            identifier_score=80,
            attribute_score=80,
            image_score=80,
            competitor_identifier=None,
        ),
        ANALYST,
    )
    validate_error(duplicate_pair, ApiErrorId.ERR_DUPLICATE_RESOURCE)

    assert review_match(first_link["id"], "REJECT")["status"] == "REJECTED"

    replacement = new_match(
        product["id"],
        competitor["id"],
        match_method="ATTRIBUTE",
        identifier_score=80,
        attribute_score=80,
        image_score=80,
        competitor_identifier=None,
    )
    assert replacement["confidence_bp"] == 8000
    assert replacement["status"] == "PROPOSED"

    links, link_meta = validate_paginated(
        api.list_matches(ANALYST, params={"product_id": product["id"]})
    )
    assert link_meta["total_count"] == 2
    assert sorted(row["status"] for row in links) == ["PROPOSED", "REJECTED"]
    _products, product_meta = validate_paginated(
        api.list_products(ANALYST, params={"market_id": market["id"]})
    )
    assert product_meta["total_count"] == 1


def test_pagination_window_is_closed_at_one_and_one_hundred(api):
    """limit 0, limit 101 and offset -1 are refused while limit 100 with offset 0 is served.

    PRD: "A `limit` that is not an integer in the range 1 through 100 inclusive, or an `offset` that is not an integer of at least 0, is rejected with `ERR_INVALID_PAGINATION` (HTTP 422)."
    Design: Corner/validations/corner_pagination_bounds_rejected_at_zero_and_101
    """
    set_clock(CLOCK)
    market = new_market(
        market_code="US-WEST",
        name="US West",
        strategic_positioning="AT_PARITY",
        strategic_index_target_bp=9800,
    )
    new_product(
        market["id"],
        sku="SKU-PG-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
    )
    new_product(
        market["id"],
        sku="SKU-PG-2",
        category_code="APPLIANCE",
        brand="Nordis",
        own_price_cents=30000,
        unit_cost_cents=12000,
    )

    for params in (
        {"market_id": market["id"], "limit": 0},
        {"market_id": market["id"], "limit": 101},
        {"market_id": market["id"], "offset": -1},
    ):
        validate_error(
            api.list_products(ANALYST, params=params),
            ApiErrorId.ERR_INVALID_PAGINATION,
        )

    rows, meta = validate_paginated(
        api.list_products(
            ANALYST, params={"market_id": market["id"], "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(rows) == 2

    page, page_meta = validate_paginated(
        api.list_products(
            ANALYST, params={"market_id": market["id"], "limit": 1, "offset": 1}
        )
    )
    assert page_meta["total_count"] == 2
    assert page_meta["has_more"] is False
    assert len(page) == 1
