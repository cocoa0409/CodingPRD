"""Catalogue foundations, inventory lots, testers and the ledger's shape."""

from test_helpers import (
    ApiErrorId,
    assert_inventory_lot,
    assert_lot_counters,
    assert_points_ledger_entry,
    assert_store,
    assert_variant,
    create_product_payload,
    create_variant_payload,
    is_valid_uuid,
    new_customer,
    new_product,
    new_store,
    new_variant,
    read_lot,
    setup_catalog,
    setup_draft_order,
    make_tester_conversion_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_STORE_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_PRODUCT_ID = "22222222-2222-4222-8222-222222222222"
UNKNOWN_LOT_ID = "66666666-6666-4666-8666-666666666666"


def test_create_store_applies_declared_defaults(api, admin_headers):
    """PRD §3.1: "Its `status` is `ACTIVE` unless the admin says otherwise, and the
    only other legal value is `PAUSED`; a paused store is one that has temporarily
    stopped taking business. A store also carries `bopis_slot_capacity` — how many
    pickup orders may occupy one sixty-minute pickup slot — which defaults to 2 and
    must be at least 1."
    PRD §2.5: "Every persisted resource carries an `id`: a server-minted UUID with no
    type prefix, unique across the system, and a `created_at`: an ISO 8601 UTC
    timestamp with three fractional digits recording when the record first came into
    being."
    PRD §2.5: "Most resources — `Store`, `Product`, `Variant`, `InventoryLot`,
    `Customer`, `Promotion`, `Order`, `OrderLine`, `Artist`, `ServiceBooking` and
    `ReturnRequest` — additionally carry `updated_at`, an ISO 8601 UTC timestamp
    refreshed on every mutation, and `version`, an integer that starts at 1 on
    creation and increments by one on every mutation of that record."

    Design: Corner/entities/create_store_returns_201_with_defaults_applied
    """
    resp = api.create_store({"name": "SEP-CA", "region_code": "CA"}, admin_headers)
    store = validate_success(resp, 201)

    assert_store(store)
    assert store["status"] == "ACTIVE", "status defaults to ACTIVE"
    assert store["bopis_slot_capacity"] == 2, "bopis_slot_capacity defaults to 2"
    assert store["version"] == 1, "version starts at 1 on creation"
    assert is_valid_uuid(store["id"]), "id is a bare UUID with no type prefix"

    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_get_store_with_unknown_id_returns_store_not_found(api, admin_headers):
    """PRD §2.9: "3. Path existence — every resource named in the URL path exists,
    checked left to right, so that the leftmost missing identifier is the one
    reported. Depending on which identifier fails, the code is `ERR_STORE_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_VARIANT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_PROMOTION_NOT_FOUND`, `ERR_ARTIST_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND` or
    `ERR_RETURN_NOT_FOUND` — all HTTP 404."

    Design: Corner/entities/get_store_with_unknown_id_returns_store_not_found
    """
    resp = api.get_store(UNKNOWN_STORE_ID, admin_headers)

    validate_error(resp, ApiErrorId.ERR_STORE_NOT_FOUND.value)
    assert resp.json()["response_type"] == "error"


def test_create_product_without_hygiene_class_is_rejected(api, admin_headers):
    """PRD §3.1: "A **Product** is a SKU family: a `name`, a `brand`, a merchandising
    `category` drawn from `SKINCARE`, `MAKEUP`, `FRAGRANCE` and `HAIR`, the
    `hygiene_class` of §2.10, and a `base_price_cents` — an integer of zero or more
    cents that variants inherit when they do not name a price of their own."
    PRD §2.9: "4. Payload shape — on every write, all required fields are present,
    every enum value is legal, every numeric field is in range, `points_redeemed` is
    an exact multiple of 100, a pickup order carries an on-the-hour
    `pickup_slot_start`, and a booked artist actually holds the skill being booked.
    Any breach is `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_product_missing_required_hygiene_class_returns_invalid_request
    """
    payload = create_product_payload()
    payload.pop("hygiene_class")

    resp = api.create_product(payload, admin_headers)

    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_variant_with_depth_index_thirteen_is_rejected(api, admin_headers):
    """PRD §3.1: "Each variant records the `product_id` of the SKU family it belongs
    to, a human `shade_name` such as "Warm Sand", the vendor's `shade_code`, a
    `finish` of `MATTE`, `DEWY` or `SATIN`, an `undertone` of `WARM`, `COOL` or
    `NEUTRAL`, and a `depth_index` positioned on a twelve-point scale where 1 is the
    lightest shade and 12 the deepest — values outside 1 through 12 inclusive are
    rejected."

    Design: Corner/entities/create_variant_with_illegal_depth_index_returns_invalid_request
    """
    product = new_product(name="Foundation", base_price_cents=4500)

    resp = api.create_variant(
        product["id"],
        create_variant_payload(
            shade_name="Too Deep", shade_code="X-13", finish="MATTE",
            undertone="WARM", depth_index=13, price_cents=4500,
        ),
        admin_headers,
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    listed, _ = validate_paginated(
        api.list_variants(admin_headers, params={"product_id": product["id"]})
    )
    assert listed == [], "the rejected variant must not have been persisted"


def test_variant_price_defaults_to_product_base_price(api, admin_headers):
    """PRD §3.1: "A variant may carry its own `price_cents`, an integer of zero or
    more; when the field is omitted, the variant sells at the product's
    `base_price_cents`."
    PRD §3.1: "When that flag is false — the default — the variant's `launch_status`
    is `NOT_LIMITED` and stays there forever; the variant has no launch gate at all."

    Design: Corner/entities/variant_price_defaults_to_product_base_price_when_omitted
    """
    product = new_product(name="Foundation", base_price_cents=4500)

    payload = create_variant_payload(
        shade_name="Ivory", shade_code="F-02", finish="DEWY",
        undertone="WARM", depth_index=2,
    )
    payload.pop("price_cents")

    variant = validate_success(
        api.create_variant(product["id"], payload, admin_headers), 201
    )

    assert_variant(variant)
    assert variant["price_cents"] == 4500, "the variant inherits base_price_cents"
    assert variant["is_limited_launch"] is False
    assert variant["launch_status"] == "NOT_LIMITED"


def test_create_variant_under_unknown_product_returns_product_not_found(
    api, admin_headers
):
    """PRD §2.11: "A request for a variant nested under a product resolves the product
    first; if the product identifier does not name an existing product, the response is
    `ERR_PRODUCT_NOT_FOUND` and the variant is never looked up."

    Design: Corner/entities/create_variant_under_unknown_product_returns_product_not_found
    """
    resp = api.create_variant(
        UNKNOWN_PRODUCT_ID,
        create_variant_payload(
            shade_name="Ghost", shade_code="G-01", finish="MATTE",
            undertone="COOL", depth_index=3, price_cents=100,
        ),
        admin_headers,
    )

    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND.value)


def test_new_inventory_lot_counters_start_from_units_received(api, admin_headers):
    """PRD §3.2: "At creation, `on_hand_units` is set equal to `units_received`, and
    `reserved_units`, `tester_units`, `sold_units` and `destroyed_units` all start at 0."
    PRD §3.2: "The earmark defaults to 0 and may be anywhere from 0 up to and
    including `units_received`."

    Design: Corner/entities/inventory_lot_computed_fields_ignore_client_supplied_values
    """
    store = new_store()
    product = new_product()
    variant = new_variant(product["id"])

    lot = validate_success(
        api.create_inventory_lot(
            {"store_id": store["id"], "variant_id": variant["id"], "units_received": 10},
            admin_headers,
        ),
        201,
    )

    assert_inventory_lot(lot)
    assert_lot_counters(
        lot,
        units_received=10,
        on_hand_units=10,
        reserved_units=0,
        tester_units=0,
        sold_units=0,
        destroyed_units=0,
        launch_reserved_units=0,
    )


def test_second_lot_for_same_store_and_variant_is_rejected(api, admin_headers):
    """PRD §3.2: "Stock lives in an **InventoryLot**, and there is exactly one lot per
    pairing of `store_id` and `variant_id`. A second attempt to create a lot for a
    pairing that already has one is rejected with `ERR_LOT_ALREADY_EXISTS` (HTTP 409)."

    Design: Corner/entities/duplicate_inventory_lot_for_same_store_and_variant_returns_lot_already_exists
    """
    ctx = setup_catalog(units_received=10)

    resp = api.create_inventory_lot(
        {
            "store_id": ctx["store"]["id"],
            "variant_id": ctx["variant"]["id"],
            "units_received": 4,
        },
        admin_headers,
    )

    validate_error(resp, ApiErrorId.ERR_LOT_ALREADY_EXISTS.value)

    assert read_lot(ctx["lot"]["id"])["units_received"] == 10, (
        "the first lot must be untouched by the rejected duplicate"
    )
    listed, meta = validate_paginated(
        api.list_inventory_lots(
            admin_headers,
            params={"store_id": ctx["store"]["id"], "variant_id": ctx["variant"]["id"]},
        )
    )
    assert meta["total_count"] == 1, "exactly one lot exists per (store, variant) pair"


def test_points_ledger_entry_has_no_version_or_updated_at(api, admin_headers):
    """PRD §2.5: "A ledger entry is append-only and immutable once written, so it
    carries only `id` and `created_at`; it has **no** `updated_at` field and **no**
    `version` field."
    PRD §3.4: "Whenever `initial_points` is greater than zero, the system does not
    simply write the number into the balance — it appends a ledger entry with
    `entry_type` of `SEED` carrying that many points as `delta_points`, so that the
    conservation rule of §2.7 holds from the very first instant."

    Design: Corner/entities/points_ledger_entry_is_immutable_and_has_no_version_field
    """
    customer = new_customer(initial_points=500)

    listed, _ = validate_paginated(
        api.list_points_ledger(admin_headers, params={"customer_id": customer["id"]})
    )
    assert len(listed) == 1, "seeding 500 points appends exactly one SEED entry"

    entry = validate_success(
        api.get_points_ledger_entry(listed[0]["id"], admin_headers)
    )

    assert_points_ledger_entry(entry)
    assert entry["entry_type"] == "SEED"
    assert entry["delta_points"] == 500
    assert entry["balance_after"] == 500
    assert "version" not in entry, "a ledger entry has no version field"
    assert "updated_at" not in entry, "a ledger entry has no updated_at field"


def test_list_orders_paginates_with_meta_counters(api, admin_headers):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope. `total_count` is the number
    of records matching the filters before pagination is applied, and `has_more` is
    true exactly when records remain beyond the current window."

    Design: Corner/entities/list_orders_paginates_with_limit_offset_total_count_and_has_more
    """
    catalog = setup_catalog(units_received=10)
    customer = new_customer()
    for _ in range(3):
        setup_draft_order(customer=customer, catalog=catalog, quantity=1)

    first_page, meta = validate_paginated(
        api.list_orders(
            admin_headers,
            params={"customer_id": customer["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(first_page) == 2, "limit=2 returns exactly 2 rows"
    assert meta["total_count"] == 3, "total_count counts matches before pagination"
    assert meta["has_more"] is True, "records remain beyond the window"
    assert meta["limit"] == 2 and meta["offset"] == 0

    second_page, meta2 = validate_paginated(
        api.list_orders(
            admin_headers,
            params={"customer_id": customer["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(second_page) == 1
    assert meta2["has_more"] is False, "nothing remains beyond the last window"

    body = api.list_orders(admin_headers, params={"customer_id": customer["id"]}).json()
    assert body["response_type"] == "array"


def test_tester_conversion_on_direct_contact_lot_is_rejected(api, associate_headers):
    """PRD §2.10: "A tester conversion against a lot whose product is
    `DIRECT_CONTACT` is rejected with `ERR_TESTER_NOT_ALLOWED` (HTTP 422), and a
    return request against a line whose product was `DIRECT_CONTACT` is rejected with
    `ERR_HYGIENE_NON_RETURNABLE` (HTTP 422)."

    Design: Corner/validations/tester_conversion_of_direct_contact_product_returns_tester_not_allowed
    """
    ctx = setup_catalog(
        units_received=10,
        product_overrides={"name": "Lip Wand", "hygiene_class": "DIRECT_CONTACT",
                           "base_price_cents": 3000},
        variant_overrides={"shade_name": "Berry", "shade_code": "BR-01",
                           "finish": "MATTE", "undertone": "COOL",
                           "depth_index": 7, "price_cents": 3000},
    )
    lot = ctx["lot"]

    resp = api.convert_testers(
        lot["id"], make_tester_conversion_payload(2, lot["version"]), associate_headers
    )

    validate_error(resp, ApiErrorId.ERR_TESTER_NOT_ALLOWED.value)

    after = read_lot(lot["id"])
    assert_lot_counters(after, tester_units=0, on_hand_units=10)


def test_tester_conversion_beyond_on_hand_units_is_rejected(api, associate_headers):
    """PRD §3.2: "The conversion succeeds only if the product is not `DIRECT_CONTACT`
    (§2.10) and only if the lot has enough units to give: if `on_hand_units` cannot
    cover the requested `units`, the request is rejected with `ERR_INSUFFICIENT_STOCK`
    (HTTP 409)."

    Design: Corner/errors/error_insufficient_stock_on_tester_conversion_beyond_on_hand
    """
    ctx = setup_catalog(units_received=3)
    lot = ctx["lot"]

    resp = api.convert_testers(
        lot["id"], make_tester_conversion_payload(5, lot["version"]), associate_headers
    )

    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)

    after = read_lot(lot["id"])
    assert_lot_counters(after, on_hand_units=3, tester_units=0)
    assert after["version"] == lot["version"], (
        "a rejected conversion must not bump the lot version"
    )


def test_tester_conversion_with_unknown_lot_returns_lot_not_found(
    api, associate_headers
):
    """PRD §2.11: "The same discipline applies to every action hung off an order, a
    lot, a booking or a return request: the parent named in the path must exist before
    any body field, any state rule or any business rule is considered."
    PRD §2.9: "8. Optimistic concurrency — the expected-version field matches the live
    parent version, per §2.8, on line addition (`ERR_STALE_ORDER_VERSION`) and tester
    conversion (`ERR_STALE_LOT_VERSION`)."

    Design: Corner/errors/error_lot_not_found_on_tester_conversion_with_unknown_lot
    """
    ctx = setup_catalog(units_received=10)
    real_lot = ctx["lot"]

    # A genuine, server-issued version — but for a different lot than the path names.
    resp = api.convert_testers(
        UNKNOWN_LOT_ID,
        make_tester_conversion_payload(1, real_lot["version"]),
        associate_headers,
    )

    validate_error(resp, ApiErrorId.ERR_LOT_NOT_FOUND.value)

    assert read_lot(real_lot["id"])["tester_units"] == 0, (
        "the untargeted lot must be untouched"
    )
