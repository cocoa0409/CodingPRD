"""Entity CRUD, defaults, computed-field, and listing corner tests
(PRD §2.3, §2.4, §3.1, §3.5).

Queue B — corner section: entities.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    is_valid_uuid,
    create_customer, create_sku, create_order,
    assert_sku, assert_customer, assert_recall_notice,
    create_sku_payload, create_customer_payload, create_order_line_payload,
    create_recall_notice_payload,
    NON_EXISTENT_UUID, TEST_USERS,
)

MGR = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["sales_associate_headers"]
ADV = TEST_USERS["service_advisor_headers"]


def test_create_sku_returns_201_with_all_fields():
    """PRD §2.4: "Every resource is assigned a server-minted `id`, a UUID string
    ... and `version`, an integer that begins at 1 on creation".
    PRD §2.6: "Each `Sku` records `on_hand` ... and exposes a computed `reserved`
    count".

    POST /shop/skus returns 201 with reserved=0, version=1, and the supplied
    on_hand.

    Design: Corner/entities/create_sku_returns_201_with_all_fields
    """
    res = api_client.create_sku(create_sku_payload(name="Chain", category="PART",
                                                   list_price_cents=2500, on_hand=7), MGR)
    sku = validate_success(res, 201)
    assert_sku(sku)
    assert sku["reserved"] == 0
    assert sku["version"] == 1
    assert sku["on_hand"] == 7


def test_get_sku_not_found_returns_404():
    """PRD §2.5: "on every request each path id and each foreign key supplied in
    the body is checked, left to right, against the store of existing resources;
    the first that fails to resolve yields `ERR_NOT_FOUND`."

    GET /shop/skus/{id} with a non-existent UUID returns ERR_NOT_FOUND (404).

    Design: Corner/entities/get_sku_not_found_returns_404
    """
    res = api_client.get_sku(NON_EXISTENT_UUID, MGR)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_sku_missing_category_returns_invalid_request():
    """PRD §3.1: "A `Sku` carries a human-readable `name`, a `category` that is
    one of `BIKE`, `PART`, or `ACCESSORY`".
    PRD §3.12: "missing or ill-typed fields ... all yield `ERR_INVALID_REQUEST`."

    POST /shop/skus omitting the required category returns ERR_INVALID_REQUEST.

    Design: Corner/entities/create_sku_missing_required_field_returns_invalid_request
    """
    payload = create_sku_payload(name="No Category", list_price_cents=1000)
    del payload["category"]
    res = api_client.create_sku(payload, MGR)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_sku_invalid_enum_category_returns_invalid_request():
    """PRD §3.12: "enum values outside their declared domain ... all yield
    `ERR_INVALID_REQUEST`."
    PRD §3.1: "a `category` that is one of `BIKE`, `PART`, or `ACCESSORY`".

    POST /shop/skus with category='GADGET' returns ERR_INVALID_REQUEST.

    Design: Corner/entities/create_sku_invalid_enum_category_returns_invalid_request
    """
    res = api_client.create_sku(create_sku_payload(name="Bad Enum", category="GADGET",
                                                   list_price_cents=1000), MGR)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_sku_defaults_on_hand_and_warranty_class():
    """PRD §3.1: "It also carries `on_hand`, which defaults to 0 ... a
    `warranty_class` of `NONE`, `COMPONENT`, or `FRAME_AND_COMPONENT` defaulting
    to `NONE`".

    Omitting on_hand and warranty_class yields on_hand=0 and warranty_class=NONE.

    Design: Corner/entities/create_sku_default_on_hand_zero_warranty_none
    """
    payload = {"name": "Defaults Sku", "category": "ACCESSORY", "list_price_cents": 3000}
    sku = validate_success(api_client.create_sku(payload, MGR), 201)
    assert sku["on_hand"] == 0
    assert sku["warranty_class"] == "NONE"


def test_create_customer_system_fields_generated():
    """PRD §3.1: "Two further customer fields are computed and never supplied on
    input: `store_credit_cents`, the running store-credit balance in cents that
    begins at 0, and `open_recall_count`, which also begins at 0."
    PRD §2.4: "`version`, an integer that begins at 1 on creation".

    POST /shop/customers mints store_credit_cents=0, open_recall_count=0,
    version=1.

    Design: Corner/entities/create_customer_system_fields_generated
    """
    res = api_client.create_customer(create_customer_payload(full_name="Sys Field",
                                                             email="sysfield@x.com"), SA)
    cust = validate_success(res, 201)
    assert_customer(cust)
    assert cust["store_credit_cents"] == 0
    assert cust["open_recall_count"] == 0
    assert cust["version"] == 1


def test_order_line_unit_price_snapshot_ignores_input():
    """PRD §3.5: "at line creation the line's `unit_price_cents` is snapshotted
    from the `Sku`'s current `list_price_cents` and is immutable thereafter."

    An OrderLine on a Sku priced 8000 has unit_price_cents=8000 regardless of any
    client-supplied value.

    Design: Corner/entities/order_line_unit_price_snapshot_ignores_input
    """
    cust = create_customer()
    sku = create_sku(name="Grip Set", category="PART", list_price_cents=8000, on_hand=5)
    order = create_order(cust["id"])
    payload = create_order_line_payload(order["id"], sku["id"], 1)
    payload["unit_price_cents"] = 1  # client value must be ignored
    line = validate_success(api_client.create_order_line(payload, SA), 201)
    assert line["unit_price_cents"] == 8000


def test_list_skus_pagination_envelope():
    """PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    GET /shop/skus?limit=1 over 2 skus returns an array with total_count=2 and
    has_more=true.

    Design: Corner/entities/list_skus_pagination_envelope
    """
    create_sku(name="Sku A", category="PART", list_price_cents=1000, on_hand=1)
    create_sku(name="Sku B", category="PART", list_price_cents=1000, on_hand=1)
    data, meta = validate_paginated(api_client.list_skus(MGR, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_list_skus_invalid_pagination_returns_400():
    """PRD §2.3: "A `limit` outside the range 1 through 100, or a negative
    `offset`, is rejected with `ERR_INVALID_PAGINATION`."

    GET /shop/skus?limit=0 violates the limit>=1 bound, returning
    ERR_INVALID_PAGINATION.

    Design: Corner/entities/list_skus_invalid_pagination_returns_400
    """
    res = api_client.list_skus(MGR, params={"limit": 0})
    validate_error(res, "ERR_INVALID_PAGINATION")


def test_duplicate_customer_email_returns_409():
    """PRD §3.1: "The email must contain an `@` character and must be unique
    across all customers, compared case-insensitively; an attempt to create a
    customer whose email duplicates an existing one — ignoring letter case — is
    rejected with `ERR_DUPLICATE_EMAIL`."

    A second customer with the same email (different case) returns
    ERR_DUPLICATE_EMAIL.

    Design: Corner/entities/duplicate_customer_email_returns_409
    """
    validate_success(api_client.create_customer(
        create_customer_payload(full_name="First", email="dup@x.com"), SA), 201)
    res = api_client.create_customer(
        create_customer_payload(full_name="Second", email="DUP@x.com"), SA)
    validate_error(res, "ERR_DUPLICATE_EMAIL")


def test_recall_notice_is_ledger_record_without_version():
    """PRD §2.4: "Four entities are append-only or immutable ledger-style records
    and therefore carry only `id` and `created_at` — they have no `updated_at`
    and no `version` field at all: `RecallNotice`, `RecallAck`, and `Payment`."

    A created RecallNotice carries id + created_at and no version field.

    Design: Corner/entities/recall_notice_immutable_no_version_field
    """
    sku = create_sku(name="Recalled Bike", category="BIKE", list_price_cents=50000, on_hand=2)
    res = api_client.create_recall_notice(
        create_recall_notice_payload(sku["id"], "ADVISORY"), MGR)
    rn = validate_success(res, 201)
    assert_recall_notice(rn)
    assert rn["sku_id"] == sku["id"]
    assert "version" not in rn
