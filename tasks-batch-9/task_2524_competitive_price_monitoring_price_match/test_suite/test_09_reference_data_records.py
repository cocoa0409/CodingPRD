"""Reference-data records: market, product, competitor and store contracts.

Every test builds its own preconditions from scratch through the PRD's own
endpoints, because the service is restarted with an empty database before each
individual test. The logical clock is pinned explicitly wherever a temporal
figure is asserted.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    MANAGER,
    ApiErrorId,
    api_client,
    assert_market,
    assert_product,
    is_iso8601_timestamp,
    is_valid_uuid,
    get_success_data,
    new_competitor,
    new_market,
    new_product,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"


def test_market_creation_returns_full_success_envelope():
    """Defining a market returns 201 with the standard envelope and every derived field benign.

    PRD: "A market's four derived fields start out empty or benign: `observed_index_bp` and `positioning_gap_bp` are both null because no report has been published yet, `insufficient_data_report_count` is 0, and `pricing_posture` is `OPEN`."
    Design: Corner/entities/corner_market_creation_returns_full_envelope
    """
    set_clock(CLOCK)

    response = api_client.create_market(
        {
            "market_code": "US-WEST",
            "name": "US West",
            "currency_code": "USD",
            "strategic_positioning": "AT_PARITY",
            "strategic_index_target_bp": 9800,
            "index_tolerance_bp": 150,
        },
        ADMIN,
    )

    data = validate_success(response, 201)
    body = response.json()
    assert body["response_type"] == "object", "a single resource is returned as an object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

    assert_market(data)
    assert data["market_code"] == "US-WEST"
    assert data["name"] == "US West"
    assert data["currency_code"] == "USD"
    assert data["strategic_positioning"] == "AT_PARITY"
    assert data["strategic_index_target_bp"] == 9800
    assert data["index_tolerance_bp"] == 150

    assert data["observed_index_bp"] is None
    assert data["positioning_gap_bp"] is None
    assert data["insufficient_data_report_count"] == 0
    assert data["pricing_posture"] == "OPEN"

    assert is_valid_uuid(data["id"]), "id is a UUID with no type prefix"
    assert "_" not in data["id"] and ":" not in data["id"]
    assert data["version"] == 1
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])


def test_product_read_returns_stored_inputs_and_margin_derived_floor():
    """Reading a product echoes its stored inputs and the margin-derived hard floor of 10000 cents.

    PRD: "The third, `effective_floor_cents`, is the hard price floor that both repricing and price matching must respect: take `unit_cost_cents`, divide it by the quantity one minus `margin_floor_pct`, and round that quotient **up** to the next whole cent; the floor is the larger of that margin-derived figure and `map_floor_cents`."
    Design: Corner/entities/corner_product_retrieval_returns_stored_and_computed_fields
    """
    set_clock(CLOCK)
    market = new_market()
    product = new_product(
        market["id"],
        sku="SKU-READ-1",
        category_code="APPLIANCE",
        brand="Vitala",
        own_price_cents=20000,
        unit_cost_cents=8000,
        margin_floor_pct=0.20,
        map_floor_cents=9000,
    )

    response = api_client.get_product(product["id"], ANALYST)

    data = validate_success(response, 200)
    assert_product(data)
    assert data["id"] == product["id"]
    assert data["market_id"] == market["id"]
    assert data["own_price_cents"] == 20000
    assert data["unit_cost_cents"] == 8000
    assert data["map_floor_cents"] == 9000
    assert data["margin_floor_pct"] == 0.20
    # ceil(8000 / 0.8) == 10000 beats the MAP floor of 9000.
    assert data["effective_floor_cents"] == 10000
    assert data["last_price_change_at"] is None
    assert data["price_change_count"] == 0
    assert data["status"] == "ACTIVE"
    assert data["index_weight_bp"] == 10000


def test_competitor_listing_reports_pagination_meta_and_tier_filter():
    """A capped competitor listing reports total_count, has_more and the effective page window.

    PRD: "The `meta` block of a list response carries `limit` (the effective page size), `offset` (the effective starting position), `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when rows remain beyond the current page)."
    Design: Corner/entities/corner_competitor_listing_pagination_envelope
    """
    set_clock(CLOCK)
    market = new_market()
    new_competitor(
        market["id"],
        competitor_code="C-A",
        name="Alpha Mart",
        collection_method="ONLINE",
        tier="PRIMARY",
    )
    new_competitor(
        market["id"],
        competitor_code="C-B",
        name="Beta Bazaar",
        collection_method="STORE_AUDIT",
        tier="PRIMARY",
    )
    new_competitor(
        market["id"],
        competitor_code="C-C",
        name="Gamma Goods",
        collection_method="HYBRID",
        tier="SECONDARY",
    )

    capped = api_client.list_competitors(
        ANALYST, params={"market_id": market["id"], "limit": 2, "offset": 0}
    )
    rows, meta = validate_paginated(capped)
    assert capped.json()["response_type"] == "array"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert len(rows) == 2

    filtered = api_client.list_competitors(
        ANALYST, params={"market_id": market["id"], "tier": "SECONDARY"}
    )
    narrowed, narrowed_meta = validate_paginated(filtered)
    assert narrowed_meta["total_count"] == 1
    assert narrowed_meta["has_more"] is False
    # limit was omitted on the second call, so the default page size applies.
    assert narrowed_meta["limit"] == 10
    assert len(narrowed) == 1
    assert narrowed[0]["competitor_code"] == "C-C"


def test_unknown_product_id_returns_not_found_error_envelope():
    """An unknown product identifier in the path yields the error envelope, not an empty object.

    PRD: "The resolution errors are `ERR_MARKET_NOT_FOUND`, `ERR_COMPETITOR_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_STORE_NOT_FOUND`, `ERR_MATCH_NOT_FOUND`, `ERR_OBSERVATION_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_RULE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` and `ERR_BATCH_NOT_FOUND`, each carrying HTTP 404."
    Design: Corner/entities/corner_product_not_found_returns_404_envelope
    """
    set_clock(CLOCK)

    response = api_client.get_product("00000000-0000-4000-8000-000000000000", ANALYST)

    error = validate_error(response, ApiErrorId.ERR_PRODUCT_NOT_FOUND)
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"].strip()
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


def test_product_create_rejects_missing_and_non_positive_own_price():
    """An absent own price and a zero own price both fail the request-shape check.

    PRD: "Required-field presence, declared type, and numeric constraints (strictly positive prices, non-negative counts, scores within 0 through 100 inclusive, ratios at least 0 and strictly below 1) — `ERR_INVALID_REQUEST`, on every creating or patching endpoint."
    Design: Corner/entities/corner_required_field_missing_on_product_create_rejected
    """
    set_clock(CLOCK)
    market = new_market()

    missing = api_client.create_product(
        {
            "market_id": market["id"],
            "sku": "SKU-MISS-1",
            "category_code": "APPLIANCE",
            "brand": "Vitala",
            "unit_cost_cents": 8000,
        },
        ADMIN,
    )
    validate_error(missing, ApiErrorId.ERR_INVALID_REQUEST)

    non_positive = api_client.create_product(
        {
            "market_id": market["id"],
            "sku": "SKU-MISS-2",
            "category_code": "APPLIANCE",
            "brand": "Vitala",
            "own_price_cents": 0,
            "unit_cost_cents": 8000,
        },
        ADMIN,
    )
    validate_error(non_positive, ApiErrorId.ERR_INVALID_REQUEST)

    _, meta = validate_paginated(
        api_client.list_products(ADMIN, params={"market_id": market["id"]})
    )
    assert meta["total_count"] == 0, "neither rejected create may persist a catalog row"


def test_optional_inputs_omitted_fall_back_to_declared_defaults():
    """Omitting every optional input across market, product, competitor and policy yields the declared defaults.

    PRD: "Four optional fields tune how aggressively the product may be repriced: `margin_floor_pct` is the minimum gross margin as a fraction of price, at least 0 and strictly below 1, defaulting to 0.20; `map_floor_cents` is the brand's minimum advertised price in cents, at least 0, defaulting to 0 to mean the brand imposes none; `brand_repricing_restricted` defaults to false and, when true, means the brand forbids automated repricing of this product; and `index_weight_bp`, which must be strictly greater than 0 and defaults to 10000, is the product's basket weight inside its category index."
    Design: Corner/entities/corner_defaults_applied_when_optional_inputs_omitted
    """
    set_clock(CLOCK)

    market = get_success_data(
        api_client.create_market(
            {
                "market_code": "US-WEST",
                "name": "US West",
                "strategic_positioning": "AT_PARITY",
                "strategic_index_target_bp": 9800,
            },
            ADMIN,
        )
    )
    assert market["currency_code"] == "USD"
    assert market["index_tolerance_bp"] == 150

    product = get_success_data(
        api_client.create_product(
            {
                "market_id": market["id"],
                "sku": "SKU-DEF-1",
                "category_code": "APPLIANCE",
                "brand": "Vitala",
                "own_price_cents": 20000,
                "unit_cost_cents": 8000,
            },
            ADMIN,
        )
    )
    assert product["margin_floor_pct"] == 0.20
    assert product["map_floor_cents"] == 0
    assert product["index_weight_bp"] == 10000
    assert product["status"] == "ACTIVE"
    assert product["brand_repricing_restricted"] is False
    # The default margin floor alone drives the computed floor: ceil(8000 / 0.8).
    assert product["effective_floor_cents"] == 10000

    competitor = get_success_data(
        api_client.create_competitor(
            {
                "market_id": market["id"],
                "competitor_code": "C-A",
                "name": "Alpha Mart",
                "collection_method": "ONLINE",
                "tier": "PRIMARY",
            },
            ADMIN,
        )
    )
    assert competitor["price_match_eligible"] is False
    assert competitor["status"] == "ACTIVE"

    policy = get_success_data(
        api_client.create_match_policy(
            {
                "market_id": market["id"],
                "eligible_competitor_tiers": ["PRIMARY"],
                "daily_override_budget_cents": 100000,
            },
            MANAGER,
        )
    )
    assert policy["verification_required"] is True
    assert policy["max_match_discount_pct"] == 0.25
    assert policy["claim_window_hours"] == 168
    assert policy["excluded_category_codes"] == []
    assert policy["status"] == "ACTIVE"
    assert policy["honored_claim_count"] == 0
