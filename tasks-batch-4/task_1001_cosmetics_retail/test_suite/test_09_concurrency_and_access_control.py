"""Optimistic concurrency, role separation, ownership, and list filters."""

from test_helpers import (
    ApiErrorId,
    add_line_payload,
    line,
    make_customer_headers,
    new_bundle_promotion,
    new_customer,
    new_gwp_promotion,
    new_lot,
    new_product,
    new_store,
    new_variant,
    read_lines,
    read_lot,
    read_order,
    setup_catalog,
    setup_confirmed_booking,
    setup_draft_order,
    setup_requested_return,
    make_tester_conversion_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_PROMOTION_ID = "33333333-3333-4333-8333-333333333333"
UNKNOWN_CUSTOMER_ID = "77777777-7777-4777-8777-777777777777"
UNKNOWN_VARIANT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
UNKNOWN_STORE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


# ─── Optimistic concurrency (PRD §2.8) ────────────────

def test_stale_lot_version_on_a_second_tester_conversion(api, associate_headers):
    """PRD §2.8: "Putting testers out on the floor writes to an `InventoryLot`, and the
    request must carry `expected_lot_version` — a required, non-optional field holding
    the `version` the associate observed when they last read that lot. If
    `expected_lot_version` does not equal the lot's current `version`, the conversion is
    rejected with `ERR_STALE_LOT_VERSION` (HTTP 412)."
    PRD §3.2: "On success, the requested count moves out of `on_hand_units` and into
    `tester_units`, and the lot's `version` increments — which is precisely why the next
    associate holding a pre-conversion version number will be turned away with
    `ERR_STALE_LOT_VERSION`."

    Design: Corner/cross_cutting_layers/stale_lot_version_on_tester_conversion_returns_412
    """
    ctx = setup_catalog(units_received=10)
    lot_id, v0 = ctx["lot"]["id"], ctx["lot"]["version"]

    first = validate_success(
        api.convert_testers(lot_id, make_tester_conversion_payload(1, v0), associate_headers)
    )
    assert first["tester_units"] == 1
    v1 = first["version"]
    assert v1 == v0 + 1

    stale = api.convert_testers(
        lot_id, make_tester_conversion_payload(1, v0), associate_headers
    )
    validate_error(stale, ApiErrorId.ERR_STALE_LOT_VERSION.value)

    retried = validate_success(
        api.convert_testers(lot_id, make_tester_conversion_payload(1, v1), associate_headers)
    )
    assert retried["tester_units"] == 2, "re-reading the version and retrying succeeds"
    assert retried["version"] == v1 + 1

    assert read_lot(lot_id)["on_hand_units"] == 8, "only two conversions landed, not three"


def test_stale_order_version_on_a_second_line_add(api, associate_headers):
    """PRD §2.8: "Adding a line to a draft order writes to an `Order`, and the request
    must carry `expected_order_version` — again required, non-optional, holding the
    `version` the client last observed on that order. If `expected_order_version` does
    not equal the order's current `version`, the line addition is rejected with
    `ERR_STALE_ORDER_VERSION` (HTTP 412)."
    PRD §2.8: "A client holding a stale quote must re-read the order before adding
    another line."

    Design: Corner/cross_cutting_layers/stale_order_version_on_line_add_returns_412
    """
    ctx = setup_draft_order(quantity=1)
    order, variant = ctx["order"], ctx["variant"]
    v0 = order["version"]

    after_add = validate_success(
        api.add_order_line(
            order["id"], add_line_payload(variant["id"], 1, v0), associate_headers
        )
    )
    assert after_add["version"] == v0 + 1

    stale = api.add_order_line(
        order["id"], add_line_payload(variant["id"], 1, v0), associate_headers
    )
    validate_error(stale, ApiErrorId.ERR_STALE_ORDER_VERSION.value)

    assert len(read_lines(order["id"])) == 2, "the rejected add created no line"
    assert read_order(order["id"])["subtotal_cents"] == 5000, (
        "the rejected add did not reprice the order"
    )


# ─── Role separation (PRD §2.1, §4) ───────────────────

def test_customer_cannot_create_products(api):
    """PRD §2.1: "If the headers are well-formed but the declared role is not among the
    roles authorised for the requested operation (see the table in §4), the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "| POST | `/products` | Create a product (SKU family) | MerchandisingAdmin |"

    Design: Corner/rbac/customer_cannot_create_products
    """
    customer = new_customer()

    resp = api.create_product(
        {
            "name": "Sneaky", "brand": "X", "category": "MAKEUP",
            "hygiene_class": "SEALED", "base_price_cents": 100,
        },
        make_customer_headers(customer["id"]),
    )

    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_store_associate_cannot_confirm_a_reschedule(api, associate_headers):
    """PRD §2.1: "If the headers are well-formed but the declared role is not among the
    roles authorised for the requested operation (see the table in §4), the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "| POST | `/service-bookings/{id}/confirm` | Accept the proposed start; the
    booking returns to CONFIRMED | BeautyArtist |"

    A StoreAssociate may cancel this very booking, but confirming a reschedule is the
    artist's alone.

    Design: Corner/rbac/store_associate_cannot_confirm_a_booking_reschedule
    """
    ctx = setup_confirmed_booking(start_at="2026-06-05T10:00:00Z", skills=["BROW"])
    booking_id = ctx["booking"]["id"]
    validate_success(
        api.reschedule_booking(
            booking_id, "2026-06-05T13:00:00Z",
            make_customer_headers(ctx["customer"]["id"]),
        )
    )

    resp = api.confirm_booking(booking_id, associate_headers)

    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    after = validate_success(api.get_service_booking(booking_id, associate_headers))
    assert after["status"] == "RESCHEDULE_PENDING"
    assert after["reschedule_count"] == 0


def test_customer_cannot_decide_their_own_return(api):
    """PRD §2.1: "If the headers are well-formed but the declared role is not among the
    roles authorised for the requested operation (see the table in §4), the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "| POST | `/return-requests/{id}/decision` | Approve or deny a return
    request | StoreAssociate |"
    PRD §3.9: "A `StoreAssociate` decides the request by supplying a `decision`."

    Design: Corner/rbac/customer_cannot_decide_their_own_return_request
    """
    ctx = setup_requested_return(quantity=1, return_quantity=1)

    resp = api.decide_return_request(
        ctx["return_request"]["id"],
        {"decision": "APPROVE"},
        make_customer_headers(ctx["customer"]["id"]),
    )

    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    read_back = validate_success(
        api.get_return_request(
            ctx["return_request"]["id"], make_customer_headers(ctx["customer"]["id"])
        )
    )
    assert read_back["status"] == "REQUESTED", "no decision was recorded"
    assert read_order(ctx["order"]["id"])["refunded_cents"] == 0, "no refund was issued"


def test_customer_cannot_read_another_customers_record(api):
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the
    acting `Customer` entity; ownership checks on any resource that references a
    `Customer` compare that resource's customer-reference field to `X-User-ID`.
    Concretely, a `Customer` may only read or mutate resources whose `customer_id`
    equals their `X-User-ID`, and an order line, return request or points-ledger entry
    inherits ownership from the order or customer it hangs off. A violation is rejected
    with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_read_another_customers_record
    """
    cust_a = new_customer()
    cust_b = new_customer()

    resp = api.get_customer(cust_a["id"], make_customer_headers(cust_b["id"]))

    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value)

    own = validate_success(
        api.get_customer(cust_a["id"], make_customer_headers(cust_a["id"]))
    )
    assert own["id"] == cust_a["id"], "a customer may read their own record"


def test_missing_auth_headers_return_unauthenticated(api, no_auth_headers):
    """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, declaring the capacity in
    which they act. If either header is absent, or if `X-User-Role` is not one of the
    four declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.9: "1. Authentication — headers present and the role recognised
    (`ERR_UNAUTHENTICATED`)."

    Authentication is step 1, so it pre-empts the 404 the unknown store would otherwise
    produce.

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    resp = api.raw_get(f"/stores/{UNKNOWN_STORE_ID}", no_auth_headers)

    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ─── List filters (PRD §4) ────────────────────────────

def test_order_lines_list_filters_by_order(api, associate_headers):
    """PRD §3.5: "Each line of the basket becomes an **OrderLine** hanging off the order
    via its `order_id`."
    PRD §4: "| GET | `/order-lines` | List order lines filtered by order, variant and/or
    promotion | MerchandisingAdmin, StoreAssociate, Customer |"
    PRD §2.3: "`total_count` is the number of records matching the filters before
    pagination is applied"

    Design: Corner/endpoints/get_order_lines_filtered_by_order_returns_only_that_orders_lines
    """
    store = new_store()
    product = new_product()
    v1 = new_variant(product["id"], shade_name="Rose", shade_code="RS-01")
    v2 = new_variant(
        product["id"], shade_name="Plum", shade_code="RS-02", finish="MATTE",
        undertone="COOL", depth_index=7,
    )
    new_lot(store["id"], v1["id"], units_received=10)
    new_lot(store["id"], v2["id"], units_received=10)
    customer = new_customer()

    order_a = validate_success(
        api.create_order(
            {
                "customer_id": customer["id"], "store_id": store["id"],
                "channel": "SHIP_FROM_STORE",
                "lines": [line(v1["id"], 1), line(v2["id"], 1)],
            },
            associate_headers,
        ),
        201,
    )
    order_b = validate_success(
        api.create_order(
            {
                "customer_id": customer["id"], "store_id": store["id"],
                "channel": "SHIP_FROM_STORE", "lines": [line(v1["id"], 1)],
            },
            associate_headers,
        ),
        201,
    )

    lines_a, meta_a = validate_paginated(
        api.list_order_lines(associate_headers, params={"order_id": order_a["id"]})
    )
    assert meta_a["total_count"] == 2
    assert all(ln["order_id"] == order_a["id"] for ln in lines_a)

    _, meta_b = validate_paginated(
        api.list_order_lines(associate_headers, params={"order_id": order_b["id"]})
    )
    assert meta_b["total_count"] == 1

    _, meta_v1 = validate_paginated(
        api.list_order_lines(associate_headers, params={"variant_id": v1["id"]})
    )
    assert meta_v1["total_count"] == 2, "one line from each order names v1"


def test_promotions_list_filters_by_gift_variant(api, admin_headers):
    """PRD §3.5: "For `GWP` and `SAMPLE`, `threshold_cents` is the minimum basket value
    at which the promotion becomes eligible (defaulting to 0, never negative),
    `gift_variant_id` names the variant that is given away, and `gift_quantity` is how
    many units of it are attached (defaulting to 1, at least 1). For `BUNDLE`,
    `gift_variant_id` is null and instead `bundle_variant_ids` holds an array of variant
    identifiers **all** of which must appear as sale lines before the bundle applies"
    PRD §4: "| GET | `/promotions` | List promotions, optionally filtered by gifted
    variant or type | MerchandisingAdmin, StoreAssociate, Customer |"

    Design: Corner/endpoints/promotions_list_filters_by_gift_variant
    """
    product = new_product(name="Kit", base_price_cents=1000)
    v_a = new_variant(product["id"], shade_name="A", shade_code="K-A", finish="MATTE",
                      undertone="WARM", depth_index=4, price_cents=1000)
    v_b = new_variant(product["id"], shade_name="B", shade_code="K-B", finish="DEWY",
                      undertone="COOL", depth_index=5, price_cents=1000)
    v_gift = new_variant(product["id"], shade_name="Gift", shade_code="K-G",
                         finish="SATIN", undertone="NEUTRAL", depth_index=6,
                         price_cents=0)

    gwp = new_gwp_promotion(v_gift["id"], 5000, name="GWP", priority=10)
    bundle = new_bundle_promotion([v_a["id"], v_b["id"]], 0.10, name="Bundle", priority=5)

    filtered, meta = validate_paginated(
        api.list_promotions(admin_headers, params={"gift_variant_id": v_gift["id"]})
    )
    assert meta["total_count"] == 1, "the BUNDLE promotion has a null gift_variant_id"
    assert filtered[0]["id"] == gwp["id"]

    everything, meta_all = validate_paginated(api.list_promotions(admin_headers))
    assert meta_all["total_count"] == 2
    assert {p["id"] for p in everything} == {gwp["id"], bundle["id"]}


# ─── Remaining not-found surfaces ─────────────────────

def test_unknown_promotion_read_returns_promotion_not_found(api, admin_headers):
    """PRD §2.9: "3. Path existence — every resource named in the URL path exists,
    checked left to right, so that the leftmost missing identifier is the one reported.
    Depending on which identifier fails, the code is `ERR_STORE_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_VARIANT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_PROMOTION_NOT_FOUND`, `ERR_ARTIST_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND` or
    `ERR_RETURN_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/error_promotion_not_found_on_unknown_promotion_read
    """
    resp = api.get_promotion(UNKNOWN_PROMOTION_ID, admin_headers)

    validate_error(resp, ApiErrorId.ERR_PROMOTION_NOT_FOUND.value)


def test_tier_checkpoint_on_an_unknown_customer_returns_customer_not_found(
    api, admin_headers
):
    """PRD §2.9: "3. Path existence — every resource named in the URL path exists,
    checked left to right, so that the leftmost missing identifier is the one reported.
    Depending on which identifier fails, the code is `ERR_STORE_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_VARIANT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_PROMOTION_NOT_FOUND`, `ERR_ARTIST_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND` or
    `ERR_RETURN_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/error_customer_not_found_on_tier_checkpoint_with_unknown_customer
    """
    resp = api.tier_checkpoint(UNKNOWN_CUSTOMER_ID, admin_headers)

    validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)


def test_order_line_naming_an_unknown_variant_returns_variant_not_found(
    api, associate_headers
):
    """PRD §2.9: "5. Body-reference existence — every foreign key inside the request
    body resolves to an existing row, reported with the same 404 family as step 3
    (`ERR_STORE_NOT_FOUND`, `ERR_VARIANT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_ARTIST_NOT_FOUND`). This
    applies to order creation, line addition, inventory-lot creation, service-booking
    creation, return-request creation and promotion creation."

    Design: Corner/errors/error_variant_not_found_on_order_line_with_unknown_variant
    """
    store = new_store()
    customer = new_customer()

    resp = api.create_order(
        {
            "customer_id": customer["id"], "store_id": store["id"],
            "channel": "SHIP_FROM_STORE",
            "lines": [line(UNKNOWN_VARIANT_ID, 1)],
        },
        associate_headers,
    )

    validate_error(resp, ApiErrorId.ERR_VARIANT_NOT_FOUND.value)

    _, meta = validate_paginated(
        api.list_orders(associate_headers, params={"customer_id": customer["id"]})
    )
    assert meta["total_count"] == 0, "neither an Order nor any OrderLine was created"
