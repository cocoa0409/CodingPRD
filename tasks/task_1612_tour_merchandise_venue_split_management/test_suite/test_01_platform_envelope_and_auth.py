"""Platform baseline: auth context, response envelopes, pagination, tour defaults."""
from test_helpers import (
    ApiErrorId,
    DEFAULT_SIZE_CURVE,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_seller,
    create_tour,
    create_tour_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

TM1 = TEST_USERS["tour_manager_headers"]
ACCT1 = TEST_USERS["accountant_headers"]


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request missing either header, carrying an unrecognized role,
    or — when the role is `Seller` — carrying an `X-User-ID` that is not the `id`
    of an existing `Seller` is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_rejected
    """
    resp = api.create_tour(
        create_tour_payload(name="NoAuth Tour"),
        headers={},
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    data, meta = validate_paginated(api.list_tours(TM1))
    assert meta["total_count"] == 0 and data == [], "no Tour row may be created"


def test_error_envelope_shape_on_failure(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/endpoints/error_envelope_shape_on_failure
    """
    resp = api.get_tour(NON_EXISTENT_UUID, TM1)
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
    body = resp.json()
    assert body["response_type"] == "error"
    validate_error(resp, ApiErrorId.ERR_TOUR_NOT_FOUND)
    assert body["meta"]["api_request_id"].startswith("req_"), (
        "error envelope must carry meta.api_request_id starting with req_")
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()


def test_not_found_family_returns_resource_specific_404s(api):
    """PRD §2.7: "Existence of every path id and every body-supplied foreign-key
    id, validated left to right — the matching one of `ERR_TOUR_NOT_FOUND`,
    `ERR_SHOW_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_SHOW_PRODUCT_NOT_FOUND`,
    `ERR_ALLOCATION_NOT_FOUND`, `ERR_SELLER_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`,
    `ERR_SALE_NOT_FOUND`, `ERR_ONLINE_ORDER_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`,
    or `ERR_SHIPMENT_NOT_FOUND` (all HTTP 404)."

    Design: Corner/errors/not_found_family_returns_resource_specific_404s
    """
    validate_error(api.get_tour(NON_EXISTENT_UUID, TM1),
                   ApiErrorId.ERR_TOUR_NOT_FOUND)
    validate_error(api.get_product(NON_EXISTENT_UUID, TM1),
                   ApiErrorId.ERR_PRODUCT_NOT_FOUND)
    validate_error(api.get_settlement(NON_EXISTENT_UUID, ACCT1),
                   ApiErrorId.ERR_SETTLEMENT_NOT_FOUND)
    validate_error(api.get_shipment(NON_EXISTENT_UUID, TM1),
                   ApiErrorId.ERR_SHIPMENT_NOT_FOUND)


def test_seller_list_pagination_envelope(api):
    """PRD §2.3: "All list endpoints accept two query parameters: `limit`,
    defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`,
    defaulting to 0. The `meta` object of a list response carries `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/seller_list_pagination_envelope
    """
    tour = create_tour(name="CD3 Tour")
    for i in range(3):
        create_seller(tour["id"], display_name=f"S{i + 1}", seller_code=f"CD3-{i + 1}")

    page1, meta1 = validate_paginated(
        api.list_sellers(TM1, params={"tour_id": tour["id"], "limit": 2, "offset": 0}))
    assert len(page1) == 2, f"limit=2 must return 2 rows, got {len(page1)}"
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_sellers(TM1, params={"tour_id": tour["id"], "limit": 2, "offset": 2}))
    assert len(page2) == 1, f"offset=2 of 3 must return 1 row, got {len(page2)}"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    _all, meta3 = validate_paginated(
        api.list_sellers(TM1, params={"tour_id": tour["id"]}))
    assert meta3["limit"] == 10 and meta3["offset"] == 0, (
        "omitting limit/offset must use defaults limit=10 offset=0")
    assert meta3["total_count"] == 3 and meta3["has_more"] is False


def test_tour_create_applies_defaults_and_initial_state(api):
    """PRD §3.1: "Two further settings shape day-to-day operations:
    `default_size_curve`, an object mapping size keys drawn from S, M, L, and XL
    to non-negative integer weights with at least one weight positive — it
    defaults to weights of 1 for S, 2 for M, 2 for L, and 1 for XL, and any curve
    that has no positive weight, carries negative or non-integer weights, or uses
    keys outside that set is rejected with `ERR_INVALID_SIZE_CURVE`; and
    `cash_variance_tolerance_cents`, the per-session cash variance magnitude at
    or below which a count-out verifies without an override, defaulting to 1000
    cents (ten dollars) and never negative."
    PRD §3.1: "A new tour's `status` starts at `PLANNING`."
    PRD §3.1: "Reading a single tour reports `royalty_payable_cents`, computed on
    read as the sum of `artist_royalty_cents` plus `licensing_cents` over the
    tour's `FINALIZED` settlements, plus the sum of `artist_royalty_final_cents`
    plus `licensing_final_cents` over the tour's `FULFILLED` online orders;
    provisional, reconciled, or disputed settlements and placed or cancelled
    orders contribute nothing."

    Design: Corner/entities/tour_create_applies_defaults_and_initial_state
    """
    # default_size_curve and cash_variance_tolerance_cents are omitted entirely.
    created = validate_success(
        api.create_tour(create_tour_payload(name="CD Tour", artist_name="Artist"),
                        TM1),
        201)
    tour = validate_success(api.get_tour(created["id"], TM1))
    assert tour["default_size_curve"] == DEFAULT_SIZE_CURVE, (
        f"default curve must be S1/M2/L2/XL1, got {tour['default_size_curve']}")
    assert tour["cash_variance_tolerance_cents"] == 1000
    assert tour["status"] == "PLANNING"
    assert isinstance(tour["version"], int) and tour["version"] >= 1
    assert tour["royalty_payable_cents"] == 0, (
        "a fresh tour has no FINALIZED settlements or FULFILLED orders")
