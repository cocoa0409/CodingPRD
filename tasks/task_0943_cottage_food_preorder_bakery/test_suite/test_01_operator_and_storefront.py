"""Operator registration, buyer registration, envelope, pagination, existence
codes and role gating on the cottage-food storefront."""
import pytest
from test_helpers import (
    ADMIN,
    INSPECTOR,
    ANNUAL_GROSS_SALES_CAP_CENTS,
    ApiErrorId,
    DEFAULT_CAP_YEAR,
    NONEXISTENT_GENERIC_ID,
    NONEXISTENT_MENU_ITEM_ID,
    NONEXISTENT_ORDER_ID,
    NONEXISTENT_WINDOW_ID,
    PERMITTED_DELIVERY_RADIUS_KM,
    add_customer,
    api_client,
    assert_baker,
    assert_customer,
    assert_order,
    create_baker,
    create_baker_payload,
    create_cookie_payload,
    create_customer_payload,
    create_order_payload,
    create_recipe,
    is_valid_uuid,
    lines_of,
    make_baker_headers,
    make_customer_headers,
    open_order,
    read_order,
    setup_held_order,
    setup_storefront,
    validate_error,
    validate_paginated,
    validate_success,
    window_version,
)


def test_operator_registration_starts_pending_with_a_zero_counted_figure(api):
    """PRD §3.1: "A newly registered operator begins in `permit_status` `PENDING`
    with `annual_gross_sales_cents` at 0 and `payout_net_cents` at 0."
    PRD §2.8: "**Annual gross sales are capped**, per operator and per calendar
    year, by `annual_cap_cents`, which defaults to 8,500,000 cents"
    PRD §2.8: "**Delivery may not leave the permitted radius**, which is recorded
    per operator as `permitted_radius_km` and defaults to 40.0 kilometres."
    PRD §2.4: "Every resource carries a server-minted `id`, which is a UUID string
    with no type prefix"

    Design: Corner/entities/baker_creation_starts_pending_with_zero_gross_sales
    """
    response = api.create_baker(create_baker_payload(), ADMIN)
    baker = validate_success(response, 201)
    assert_baker(baker)
    assert baker["permit_status"] == "PENDING"
    assert baker["annual_gross_sales_cents"] == 0
    assert baker["payout_net_cents"] == 0
    assert baker["annual_cap_cents"] == ANNUAL_GROSS_SALES_CAP_CENTS
    assert baker["cap_year"] == DEFAULT_CAP_YEAR
    assert baker["permitted_radius_km"] == pytest.approx(PERMITTED_DELIVERY_RADIUS_KM)
    assert baker["version"] == 1
    assert is_valid_uuid(baker["id"]) and not baker["id"].startswith("baker")

    # A body foreign key that does not resolve is rung 10's ERR_RESOURCE_NOT_FOUND.
    orphan = api.create_customer(
        create_customer_payload(NONEXISTENT_GENERIC_ID), ADMIN
    )
    validate_error(orphan, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


def test_operator_listing_is_paginated_and_ordered_by_created_at(api):
    """PRD §2.3: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100."
    PRD §2.3: "List results are ordered by `created_at` ascending unless a specific
    endpoint narrative says otherwise."
    PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` (the number of records matching the filters before the page
    window is applied) and `has_more` (true when records remain beyond the current
    page)."

    Design: Corner/entities/baker_retrieval_and_listing_are_paginated
    """
    first = create_baker(display_name="Hearth and Crumb", jurisdiction_code="CA-ALAMEDA")
    second = create_baker(display_name="Rise and Shine", jurisdiction_code="CA-SONOMA")
    third = create_baker(display_name="Third Loaf", jurisdiction_code="CA-MARIN")

    page_one = api.list_bakers(ADMIN, {"limit": 2, "offset": 0})
    data, meta = validate_paginated(page_one)
    body = page_one.json()
    assert body["response_type"] == "array"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert len(data) == 2

    page_two = api.list_bakers(ADMIN, {"limit": 2, "offset": 2})
    data_two, meta_two = validate_paginated(page_two)
    assert len(data_two) == 1
    assert meta_two["has_more"] is False
    # The two pages together partition the three operators, with no repetition.
    paged = [row["id"] for row in data] + [row["id"] for row in data_two]
    assert sorted(paged) == sorted([first["id"], second["id"], third["id"]])

    single = validate_success(api.get_baker(second["id"], ADMIN))
    assert single["display_name"] == "Rise and Shine"


def test_buyer_registration_applies_every_declared_optional_default(api):
    """PRD §3.1: "Three optional fields shape later handoffs: `allergen_avoidances`,
    an array of objects each pairing an `allergen` string with a `severity` of
    `ANAPHYLACTIC` or `INTOLERANCE`, defaulting to empty; `unattended_consent`, a
    standing consent to unattended porch handoff, defaulting to false; and
    `cooler_provided`, recording that the buyer will leave a cooler out for
    temperature-sensitive porch handoffs, also defaulting to false. A new customer
    starts with `credit_balance_cents` at 0."

    Design: Corner/entities/customer_defaults_applied_when_optional_fields_omitted
    """
    baker = create_baker()
    response = api.create_customer(
        {
            "baker_id": baker["id"],
            "display_name": "Minimal Customer",
            "email": "min@example.com",
            "delivery_distance_km": 3.5,
        },
        ADMIN,
    )
    customer = validate_success(response, 201)
    assert_customer(customer)
    assert customer["allergen_avoidances"] == []
    assert customer["unattended_consent"] is False
    assert customer["cooler_provided"] is False
    assert customer["credit_balance_cents"] == 0
    assert customer["version"] == 1


def test_pagination_limit_beyond_one_hundred_is_a_malformed_request(api):
    """PRD §2.3: "A `limit` outside the range 1 through 100, or a negative `offset`,
    is a malformed request and is rejected with `ERR_VALIDATION` (HTTP 400)."
    PRD §2.3: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100."

    Design: Corner/entities/pagination_limit_out_of_range_returns_validation
    """
    baker = create_baker()
    headers = make_baker_headers(baker["id"])
    rejected = api.list_menu_items(
        headers, {"baker_id": baker["id"], "limit": 101, "offset": 0}
    )
    validate_error(rejected, ApiErrorId.ERR_VALIDATION)

    accepted = api.list_menu_items(headers, {"baker_id": baker["id"]})
    _, meta = validate_paginated(accepted)
    assert meta["limit"] == 10


def test_unresolvable_offer_window_path_segment_has_its_own_code(api):
    """PRD §2.6: "Rung 5: an `offer_window_id` appearing in the path resolves to an
    offer window, otherwise `ERR_OFFER_WINDOW_NOT_FOUND` (404); this applies to
    every endpoint whose path contains that segment."

    Design: Corner/entities/offer_window_path_id_returns_window_specific_not_found
    """
    create_baker()
    response = api.get_offer_window(NONEXISTENT_WINDOW_ID, ADMIN)
    error = validate_error(response, ApiErrorId.ERR_OFFER_WINDOW_NOT_FOUND)
    assert error["error_id"] != "ERR_RESOURCE_NOT_FOUND"


def test_line_add_under_a_missing_order_reports_the_order_before_the_menu_item(api):
    """PRD §2.6: "Rung 6: an `order_id`, and then an `order_line_id`, appearing in
    the path resolves, evaluated left to right, otherwise `ERR_ORDER_NOT_FOUND`
    (404); this applies to every endpoint whose path contains either segment,
    including the standalone order-line read."
    PRD §2.4: "Path parameters are validated left to right."

    Design: Corner/entities/line_add_under_nonexistent_order_returns_order_not_found
    """
    s = setup_storefront()
    response = api.add_order_line(
        NONEXISTENT_ORDER_ID,
        {
            "menu_item_id": NONEXISTENT_GENERIC_ID,
            "quantity": 13,
            "expected_offer_window_version": s.window["version"],
        },
        s.ch,
    )
    error = validate_error(response, ApiErrorId.ERR_ORDER_NOT_FOUND)
    assert error["error_id"] != "ERR_MENU_ITEM_NOT_FOUND"


def test_unresolvable_body_menu_item_has_its_own_code(api):
    """PRD §2.6: "Rung 9: a body `menu_item_id` resolves, otherwise
    `ERR_MENU_ITEM_NOT_FOUND` (404); this applies to line addition, subscription
    creation, and review submission."

    Design: Corner/entities/menu_item_body_id_returns_menu_item_not_found
    """
    s = setup_storefront()
    order = open_order(s.customer_id, s.window_id)
    response = api.add_order_line(
        order["id"],
        {
            "menu_item_id": NONEXISTENT_MENU_ITEM_ID,
            "quantity": 13,
            "expected_offer_window_version": s.window["version"],
        },
        s.ch,
    )
    validate_error(response, ApiErrorId.ERR_MENU_ITEM_NOT_FOUND)


def test_order_creation_without_a_handoff_mode_is_rejected(api):
    """PRD §2.6: "Rung 13, on every creating or modifying endpoint: every required
    body field is present with its declared type, integers are zero or greater
    wherever the field is a quantity or an amount, and a review's `rating` is
    between 1 and 5 inclusive; violations are `ERR_VALIDATION` (400)."
    PRD §3.5: "A buyer opens an order against an `OPEN` window by naming the
    `customer_id` and the `offer_window_id` together with the `handoff_mode` that
    selects the fulfilment pipeline"

    Design: Corner/entities/order_create_missing_handoff_mode_returns_validation
    """
    s = setup_storefront()
    response = api.create_order(
        {"customer_id": s.customer_id, "offer_window_id": s.window_id}, s.ch
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION)

    orders = validate_success(
        api.list_orders(s.ch, {"customer_id": s.customer_id})
    )
    assert orders == []


def test_order_creation_ignores_supplied_system_fields(api):
    """PRD §3.5: "A new order is created with `order_status` `DRAFT`,
    `payment_status` `UNPAID`, `handoff_status` `NOT_SCHEDULED`, `source` `WALKUP`,
    and `prepaid` false"
    PRD §3.5: "An order in `DRAFT` holds nothing and has a null `placed_at`."
    PRD §2.4: "`version`, an integer that starts at 1 on creation and increments by
    exactly 1 on each mutation of that resource."

    Design: Corner/entities/order_create_system_fields_input_ignored
    """
    s = setup_storefront()
    response = api.create_order(
        {
            "customer_id": s.customer_id,
            "offer_window_id": s.window_id,
            "handoff_mode": "PICKUP_COUNTER",
            "order_status": "FULFILLED",
            "payment_status": "CAPTURED",
            "version": 99,
        },
        s.ch,
    )
    order = validate_success(response, 201)
    assert_order(order)
    assert order["order_status"] == "DRAFT"
    assert order["payment_status"] == "UNPAID"
    assert order["handoff_status"] == "NOT_SCHEDULED"
    assert order["source"] == "WALKUP"
    assert order["prepaid"] is False
    assert order["version"] == 1
    assert order["placed_at"] is None
    assert order["hold_expires_at"] is None


def test_line_add_with_an_undeclared_disposition_is_an_enum_failure(api):
    """PRD §2.6: "Rung 14, on the same endpoints: every enum-valued body field
    carries a member of that field's declared value set, otherwise
    `ERR_INVALID_ENUM` (400)."
    PRD §2.6: "This enum routing is **exhaustive and closed**: `channel`,
    `handoff_mode`, `disposition`, `pricing_basis`, `product_class`, `oven_profile`,
    `cadence`, `billing_mode`, `tip_mode`, `outcome`, `to_status`, `mode`,
    `movement_kind`, and the `severity` member of an allergen-avoidance entry all
    route here"

    Design: Corner/entities/line_add_invalid_enum_disposition_rejected
    """
    s = setup_storefront()
    order = open_order(s.customer_id, s.window_id)
    response = api.add_order_line(
        order["id"],
        {
            "menu_item_id": s.cookie_id,
            "quantity": 13,
            "disposition": "TOASTED",
            "expected_offer_window_version": s.window["version"],
        },
        s.ch,
    )
    error = validate_error(response, ApiErrorId.ERR_INVALID_ENUM)
    assert error["error_id"] != "ERR_VALIDATION"
    assert read_order(order["id"], s.ch)["order_status"] == "DRAFT"
    window = validate_success(api.get_offer_window(s.window_id, s.ch))
    assert window["held_units"] == 0


def test_a_request_without_auth_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to every endpoint must carry two headers:
    `X-User-ID` and `X-User-Role`. If either header is absent or empty, the request
    is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.6: "Rung 1: both `X-User-Role` and `X-User-ID` are present and
    non-empty, otherwise `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/roles/menu_items_list_missing_auth_headers_unauthenticated
    """
    baker = create_baker()
    anonymous = api.raw_get(
        "/menu-items", headers={"Content-Type": "application/json"},
        params={"baker_id": baker["id"]},
    )
    validate_error(anonymous, ApiErrorId.ERR_UNAUTHENTICATED)

    authenticated = api.list_menu_items(
        make_baker_headers(baker["id"]), {"baker_id": baker["id"]}
    )
    data, _ = validate_paginated(authenticated)
    assert data == []


def test_health_inspector_cannot_create_a_menu_item(api):
    """PRD §2.6: "Rung 3: the acting role appears in the called endpoint's
    authorised-role list, otherwise `ERR_UNAUTHORIZED` (403)."
    PRD §2.1: "The health inspector is strictly read-only: it appears in the
    authorised-role list of exactly eighteen read endpoints (operators and their
    compliance summary, recipes and recipe components, allergen profiles,
    ingredient lots, menu items, offer windows, batches, and labels) and of no
    write endpoint anywhere in the system."

    Design: Corner/roles/health_inspector_cannot_create_a_menu_item
    """
    baker = create_baker()
    recipe = create_recipe(baker["id"])
    response = api.create_menu_item(
        create_cookie_payload(baker["id"], recipe["id"]), INSPECTOR
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

    inspector_read = api.list_menu_items(INSPECTOR, {"baker_id": baker["id"]})
    _, meta = validate_paginated(inspector_read)
    assert meta["total_count"] == 0

    baker_read = api.list_menu_items(
        make_baker_headers(baker["id"]), {"baker_id": baker["id"]}
    )
    _, baker_meta = validate_paginated(baker_read)
    assert baker_meta["total_count"] == 0


def test_baker_cannot_confirm_an_order(api):
    """PRD §2.6: "Rung 3: the acting role appears in the called endpoint's
    authorised-role list, otherwise `ERR_UNAUTHORIZED` (403)."
    PRD §3.5: "Confirmation converts a hold into a commitment. It is available to
    the buyer from `PENDING_HOLD` only"

    Design: Corner/roles/baker_cannot_confirm_an_order
    """
    s = setup_held_order()
    response = api.confirm_order(s.order_id, s.bh, {})
    error = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
    assert error["error_id"] != "ERR_NOT_RESOURCE_OWNER"
    assert read_order(s.order_id, s.ch)["order_status"] == "PENDING_HOLD"
    window = validate_success(api.get_offer_window(s.window_id, s.bh))
    assert window["confirmed_units"] == 0


def test_a_buyer_cannot_confirm_another_buyers_order(api):
    """PRD §2.6: "Rung 11: when the acting role is `Customer`, `X-User-ID` equals
    the `customer_id` that owns the target order, subscription, club cycle,
    payment, or review, otherwise `ERR_NOT_RESOURCE_OWNER` (403); this applies to
    every `Customer`-callable endpoint operating on an existing resource."

    Design: Corner/roles/customer_cannot_confirm_another_customers_order
    """
    s = setup_held_order()
    intruder = add_customer(
        s, "intruder", display_name="Intruder Ivy", email="ivy@example.com",
        delivery_distance_km=5.0,
    )
    response = api.confirm_order(
        s.order_id, make_customer_headers(intruder["id"]), {}
    )
    error = validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert error["error_id"] != "ERR_UNAUTHORIZED"

    owner = validate_success(api.confirm_order(s.order_id, s.ch, {}))
    assert owner["order_status"] == "CONFIRMED"
    assert owner["subtotal_cents"] == 4600
