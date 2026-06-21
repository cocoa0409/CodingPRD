"""Order/line/payment creation, not-found and reference checks, pagination, RBAC,
balance-payment OCC, and FK reverse-reachability listings."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NONEXISTENT_UUID,
    make_customer_headers,
    make_staff_headers,
    make_dispatcher_headers,
    order_payload,
    line_payload,
    balance_payment_payload,
    assert_order,
    assert_payment,
    assert_payment_is_immutable_ledger,
)
import test_helpers.fixtures as fx


# ---------------------------------------------------------------------------
# Queue B: entities — order creation, required/reference/not-found
# ---------------------------------------------------------------------------
def test_create_order_returns_draft_unpaid_with_system_fields(api):
    """PRD 3.3: "On creation the server freezes `placed_at` to the current time,
    sets `production_status` to `DRAFT`, and sets `payment_status` to `UNPAID`."
    PRD 2.4: "`version` - an integer that starts at its initial value and increments
    by one on every mutation."

    Design: Corner/entities/create_order_returns_201_with_system_fields
    """
    ctx = fx.setup_catalog(product_overrides={"name": "Basic"})
    customer = ctx["customer"]
    headers = make_customer_headers(customer["id"])
    data = validate_success(
        api.create_order(order_payload(customer["id"], ctx["product"]["id"],
                                       ctx["production_day"]["id"]), headers), 201)
    assert_order(data)
    assert data["production_status"] == "DRAFT", data
    assert data["payment_status"] == "UNPAID", data
    assert data["version"] == 1, data


def test_create_order_missing_product_id_invalid_request(api):
    """PRD 3.3: "the create payload supplies `customer_id`, `product_id`, and
    `production_day_id`."
    PRD 2.10: "Malformed bodies, missing required fields, bad enum values, and
    out-of-range numerics (such as a `window_start_min` outside the 0-to-1439 range
    or `units` below 1) are rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_order_missing_product_id_returns_invalid_request
    """
    fx.set_clock()
    pday = fx.create_production_day()
    customer = fx.create_customer()
    headers = make_customer_headers(customer["id"])
    validate_error(
        api.create_order({"customer_id": customer["id"], "production_day_id": pday["id"]}, headers),
        ApiErrorId.ERR_INVALID_REQUEST)


def test_get_order_nonexistent_id_not_found(api):
    """PRD 2.6: "the system validates them left-to-right and rejects on the *first*
    identifier that does not resolve to a row, returning `ERR_NOT_FOUND`."

    Design: Corner/entities/get_order_nonexistent_id_returns_not_found
    """
    customer = fx.create_customer()
    headers = make_customer_headers(customer["id"])
    validate_error(api.get_order(NONEXISTENT_UUID, headers), ApiErrorId.ERR_NOT_FOUND)


def test_create_order_unknown_production_day_reference_not_found(api):
    """PRD 2.6: "When a body names a `product_id`, `production_day_id`,
    `customer_id`, or `route_id` that does not resolve ... the request is rejected
    with `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/entities/create_order_unknown_production_day_returns_reference_not_found
    """
    product = fx.create_product(name="Ref")
    customer = fx.create_customer()
    headers = make_customer_headers(customer["id"])
    validate_error(
        api.create_order(order_payload(customer["id"], product["id"],
                                       "11111111-1111-4111-8111-111111111111"), headers),
        ApiErrorId.ERR_REFERENCE_NOT_FOUND)


def test_line_effective_allergens_union_and_surcharge(api):
    """PRD 3.3: "`line_surcharge_cents` is the sum of `surcharge_cents` across the
    line's selected options, multiplied by the line's `units`. `effective_allergen_codes`
    is the union of the product's `declared_allergen_codes` with the
    `introduces_allergen_codes` of every selected option."

    Product declares EGG; MARZIPAN(+800) introduces NUT; units=2 ->
    line_surcharge 1600, effective allergens contain EGG and NUT.

    Design: Corner/entities/line_computed_effective_allergens_union
    """
    order, customer, product, pday = fx.setup_draft_order(
        product_overrides={"name": "Allergen", "allowed_option_codes": ["MARZIPAN"],
                           "declared_allergen_codes": ["EGG"]},
        options=[("MARZIPAN", 800, {"introduces_allergen_codes": ["NUT"]})],
    )
    headers = make_customer_headers(customer["id"])
    line = validate_success(
        api.add_line(order["id"],
                     line_payload(units=2, selected_option_codes=["MARZIPAN"]), headers), 201)
    assert line["line_surcharge_cents"] == 1600, line
    assert "EGG" in line["effective_allergen_codes"], line
    assert "NUT" in line["effective_allergen_codes"], line


def test_deposit_payment_is_immutable_ledger_entry(api):
    """PRD 2.4: "a payment is an immutable ledger entry and therefore carries only
    `id` and `created_at`. A `Payment` has no `updated_at` and no `version`, and is
    never mutated after it is recorded."
    PRD 3.7: "The settlement creates a `Payment` whose `kind` is `DEPOSIT` and whose
    `amount_cents` equals `deposit_due_cents`."

    A 10000 estimate yields a 5000 deposit (floor); the Payment has no version.

    Design: Corner/entities/payment_immutable_entity_has_no_version_field
    """
    order, customer, product, pday = fx.setup_quoted_order(units=1)
    headers = make_customer_headers(customer["id"])
    payment = validate_success(api.post_payment(order["id"], {"kind": "DEPOSIT"}, headers), 201)
    assert_payment(payment)
    assert payment["amount_cents"] == 5000, payment
    assert_payment_is_immutable_ledger(payment)


# ---------------------------------------------------------------------------
# Queue B: entities — pagination
# ---------------------------------------------------------------------------
def test_order_list_pagination_envelope(api):
    """PRD 2.3: "List responses carry the pagination bookkeeping in the `meta`
    object of the envelope, namely `limit`, `offset`, `total_count`, and `has_more`."

    Two DRAFT orders for one customer, limit=1 -> total_count 2 and has_more true.

    Design: Corner/entities/order_list_pagination_envelope
    """
    ctx = fx.setup_catalog(product_overrides={"name": "Pg"})
    customer = ctx["customer"]
    headers = make_customer_headers(customer["id"])
    fx.create_order(customer, ctx["product"], ctx["production_day"])
    fx.create_order(customer, ctx["product"], ctx["production_day"])
    data, meta = validate_paginated(
        api.list_orders(headers, params={"customer_id": customer["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
    assert len(data) == 1, data


def test_pagination_limit_over_max_rejected(api):
    """PRD 2.3: "The `limit` parameter caps the number of items returned; it defaults
    to 10, with a minimum of 1 and a maximum of 100. ... A `limit` or `offset`
    outside these bounds is rejected with `ERR_VALIDATION_PAGINATION`."

    Design: Corner/entities/pagination_limit_over_max_returns_validation_error
    """
    customer = fx.create_customer()
    headers = make_customer_headers(customer["id"])
    validate_error(api.list_orders(headers, params={"limit": 500}),
                   ApiErrorId.ERR_VALIDATION_PAGINATION)


# ---------------------------------------------------------------------------
# Queue B: rbac
# ---------------------------------------------------------------------------
def test_staff_cannot_create_order(api):
    """PRD 2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    POST /orders is Customer-exclusive; BakeryStaff is rejected.

    Design: Corner/rbac/staff_cannot_post_order
    """
    ctx = fx.setup_catalog(product_overrides={"name": "RbacP"})
    validate_error(
        api.create_order(order_payload(ctx["customer"]["id"], ctx["product"]["id"],
                                       ctx["production_day"]["id"]),
                         make_staff_headers("staff-1")),
        ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_customer_cannot_quote_other_customers_order(api):
    """PRD 2.1: "for any customer-owned action under an order, the order's
    `customer_id` must equal the caller's `X-User-ID`; a mismatch is rejected with
    `ERR_NOT_ORDER_OWNER`."

    Design: Corner/rbac/customer_cannot_act_on_other_customers_order
    """
    fx.set_clock()
    product = fx.create_product(name="Owner")
    pday = fx.create_production_day()
    cust_a = fx.create_customer(email=fx.unique_email("owner-a"))
    cust_b = fx.create_customer(email=fx.unique_email("owner-b"))
    order = fx.create_order(cust_a, product, pday)
    fx.add_line(order, cust_a, units=1)
    headers_b = make_customer_headers(cust_b["id"])
    validate_error(api.quote_order(order["id"], {}, headers_b), ApiErrorId.ERR_NOT_ORDER_OWNER)


def test_missing_headers_returns_unauthenticated(api):
    """PRD 2.1: "If either header is missing, or `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    A GET /orders with no auth headers -> ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    validate_error(api.list_orders({}), ApiErrorId.ERR_UNAUTHENTICATED)


# ---------------------------------------------------------------------------
# Queue B: cross_cutting — balance-payment OCC
# ---------------------------------------------------------------------------
def test_balance_capture_stale_version_rejected(api):
    """PRD 2.7: "A balance-payment request must carry `expected_order_version`
    matching the order's current `version`. If final pricing was re-approved or a
    credit adjustment moved the figures since the customer last read the order, the
    order's `version` will have advanced and the capture is rejected with
    `ERR_STALE_ORDER_VERSION` (HTTP 412)".

    A stale (current-1) version keeps payment_status at DEPOSIT_PAID.

    Design: Corner/cross_cutting_complexity_layers/balance_capture_stale_order_version_412
    """
    order, customer, proof, product, pday = fx.setup_proof_approved_order(units=2)
    headers = make_customer_headers(customer["id"])
    fresh = validate_success(api.get_order(order["id"], headers), 200)
    validate_error(
        api.post_balance_payment(order["id"],
                                 balance_payment_payload(fresh["version"] - 1, 0), headers),
        ApiErrorId.ERR_STALE_ORDER_VERSION)
    after = validate_success(api.get_order(order["id"], headers), 200)
    assert after["payment_status"] == "DEPOSIT_PAID", after


def test_balance_capture_correct_version_succeeds(api):
    """PRD 3.10: "A successful capture advances the payment status from
    `DEPOSIT_PAID` to `PAID_IN_FULL`."
    PRD 2.7: "A balance-payment request must carry `expected_order_version` matching
    the order's current `version`."

    A 14000 balance with the correct version succeeds and lands PAID_IN_FULL.

    Design: Corner/cross_cutting_complexity_layers/balance_capture_correct_version_succeeds
    """
    order, customer, proof, product, pday = fx.setup_proof_approved_order(units=2)
    headers = make_customer_headers(customer["id"])
    fresh = validate_success(api.get_order(order["id"], headers), 200)
    payment = validate_success(
        api.post_balance_payment(order["id"], balance_payment_payload(fresh["version"], 0), headers), 201)
    assert payment["amount_cents"] == 14000, payment
    after = validate_success(api.get_order(order["id"], headers), 200)
    assert after["payment_status"] == "PAID_IN_FULL", after


# ---------------------------------------------------------------------------
# Queue B: endpoints — FK reverse-reachability listings
# ---------------------------------------------------------------------------
def test_list_order_lines(api):
    """PRD 3.14: "The children of an order are reachable through their own listings
    - its customization lines, its proofs, its payments, and its slot reservations".

    Design: Corner/endpoints/list_lines_reverse_reachability
    """
    order, customer, product, pday = fx.setup_draft_order(product_overrides={"name": "ListLines"})
    headers = make_customer_headers(customer["id"])
    fx.add_line(order, customer, units=1)
    data, meta = validate_paginated(api.list_lines(order["id"], headers))
    assert len(data) == 1, data


def test_list_order_proofs(api):
    """PRD 3.14: "The children of an order are reachable through their own listings
    - its customization lines, its proofs, its payments, and its slot reservations".

    Design: Corner/endpoints/list_proofs_reverse_reachability
    """
    order, customer, proof, product, pday = fx.setup_proof_pending_order(units=1)
    headers = make_customer_headers(customer["id"])
    data, meta = validate_paginated(api.list_proofs(order["id"], headers))
    assert len(data) == 1, data


def test_list_order_payments(api):
    """PRD 3.14: "The children of an order are reachable through their own listings
    - its customization lines, its proofs, its payments, and its slot reservations".

    Design: Corner/endpoints/list_payments_reverse_reachability
    """
    order, customer, product, pday = fx.setup_deposit_paid_order(units=1)
    headers = make_customer_headers(customer["id"])
    data, meta = validate_paginated(api.list_payments(order["id"], headers))
    assert len(data) == 1, data


def test_list_order_slots(api):
    """PRD 3.14: "The children of an order are reachable through their own listings
    - its customization lines, its proofs, its payments, and its slot reservations".

    Design: Corner/endpoints/list_order_slots_reverse_reachability
    """
    order, customer, proof, product, pday = fx.setup_proof_approved_order(units=1)
    fx.create_slot(order, customer, "PICKUP")
    headers = make_customer_headers(customer["id"])
    data, meta = validate_paginated(api.list_slots(order["id"], headers))
    assert len(data) == 1, data


def test_list_route_committed_reservations(api):
    """PRD 3.14: "a route's committed reservations and a production day's bound
    orders are likewise listable for the operational roles."

    Design: Corner/endpoints/list_route_reservations_reverse_reachability
    """
    route = fx.create_route(route_name="R2", service_date="2026-06-20", stop_minutes=30)
    order, customer, reservation, product, pday = fx.setup_committed_delivery_order(
        window_start_min=480, route=route, units=1)
    dispatcher = make_dispatcher_headers()
    data, meta = validate_paginated(api.list_route_reservations(route["id"], dispatcher))
    assert len(data) == 1, data


def test_list_production_day_orders(api):
    """PRD 3.14: "a route's committed reservations and a production day's bound
    orders are likewise listable for the operational roles."

    Design: Corner/endpoints/list_production_day_orders_reverse_reachability
    """
    ctx = fx.setup_catalog(product_overrides={"name": "PdayOrders"})
    fx.create_order(ctx["customer"], ctx["product"], ctx["production_day"])
    manager = fx.MANAGER
    data, meta = validate_paginated(
        api.list_production_day_orders(ctx["production_day"]["id"], manager))
    assert len(data) == 1, data
