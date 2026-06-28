"""Catalog/customer CRUD, defaults, computed fields, uniqueness, pagination,
shipment/membership conflicts, OCC stale-version, and RBAC denials.

Covers corner queues entities, endpoints, errors (non-stub), and rbac.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, make_customer_headers, fixtures as fx,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── Corner: entities ───────────────────────────────────────────────────────
def test_register_customer_returns_201_with_defaults(api):
    """PRD §3.2: "A new customer is born with `age_verified` false, `compliance_status` set to `CLEAR`, and `lifetime_spend_cents` at 0."

    Design: Corner/entities/register_customer_returns_201_with_defaults
    """
    resp = api_client.register_customer(
        {"email": "e1@x.com", "full_name": "E One",
         "date_of_birth": "2000-01-01", "ship_state_code": "CA"}, ANON)
    cust = validate_success(resp, expected_status=201)

    assert cust["compliance_status"] == "CLEAR"
    assert cust["age_verified"] is False
    assert cust["lifetime_spend_cents"] == 0


def test_get_customer_not_found_returns_404(api):
    """PRD §2.6: "the system validates the identifiers left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource."

    Design: Corner/entities/get_customer_not_found_returns_404
    """
    resp = api_client.get_customer(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_product_missing_field_returns_missing_field(api):
    """PRD §2.10: "the presence and typing of required body fields surface as `ERR_MISSING_FIELD` (HTTP 400)."
    PRD §3.1: "A **Product** is the stable catalog entry created by an `Admin` with a `sku` ... a `category`, a `container_type` ..."

    Design: Corner/entities/create_product_missing_required_field_returns_missing_field
    """
    resp = api_client.create_product(
        {"sku": "X-1", "name": "X", "container_type": "BOTTLE",
         "bottle_volume_ml": 750, "abv_pct": 13.00}, ADMIN)  # no category
    validate_error(resp, ApiErrorId.ERR_MISSING_FIELD.value)


def test_create_product_invalid_category_returns_invalid_request(api):
    """PRD §3.1: "The `category` is one of `WINE`, `SPIRITS`, `BEER`, `GROWLER`, or `KEG`"
    PRD §2.10: "Field-level validity checks — legal enum values ... surface as `ERR_INVALID_REQUEST` (HTTP 400)"

    Design: Corner/entities/create_product_invalid_category_enum_returns_invalid_request
    """
    resp = api_client.create_product(
        {"sku": "X-2", "name": "X", "category": "CIDER", "container_type": "BOTTLE",
         "bottle_volume_ml": 750, "abv_pct": 13.00}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_product_is_allocated_defaults_false(api):
    """PRD §3.1: "A product may be flagged as allocation-controlled through the optional `is_allocated` boolean, which defaults to false when omitted"
    PRD §3.1: "On creation a product's `status` is initialized to `ACTIVE`"

    Design: Corner/entities/product_is_allocated_default_false_applied
    """
    resp = api_client.create_product(
        {"sku": "X-3", "name": "X3", "category": "WINE", "container_type": "BOTTLE",
         "bottle_volume_ml": 750, "abv_pct": 13.00}, ADMIN)
    prod = validate_success(resp, expected_status=201)

    assert prod["is_allocated"] is False
    assert prod["status"] == "ACTIVE"


def test_product_min_purchase_age_always_21(api):
    """PRD §3.1: "Regardless of category or alcohol content — including beer below eight percent alcohol by volume — `min_purchase_age` is always set to 21 years, the US federal floor for all alcohol. The field exists so that callers and tests can rely on it being exactly 21 and never read from any other source."

    Design: Corner/entities/product_min_purchase_age_computed_is_21_input_ignored
    """
    resp = api_client.create_product(
        {"sku": "X-4", "name": "X4", "category": "SPIRITS", "container_type": "BOTTLE",
         "bottle_volume_ml": 750, "abv_pct": 40.00}, ADMIN)
    prod = validate_success(resp, expected_status=201)
    assert prod["min_purchase_age"] == 21


def test_idscan_created_pending_no_version_field(api):
    """PRD §2.4: "Two entities are append-only audit records and carry only `id` and `created_at`; they have neither `updated_at` nor `version`. The first is `IdScan`, the record of a single identity-document scan."
    PRD §3.2: "The scan is created in `PENDING` status."

    Design: Corner/entities/idscan_immutable_no_version_field
    """
    cust = fx.register_customer("im1@x.com", ship_state_code="CA")
    resp = api_client.create_id_scan(
        {"customer_id": cust["id"], "id_state_code": "CA",
         "id_expiry_date": "2030-01-01", "scanned_dob": "2000-01-01"}, ASSOCIATE)
    scan = validate_success(resp, expected_status=201)

    assert scan["status"] == "PENDING"
    assert "version" not in scan, "IdScan must not carry a version field"
    assert "updated_at" not in scan, "IdScan must not carry an updated_at field"


def test_list_customers_pagination_envelope(api):
    """PRD §2.3: "List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the response envelope's `meta` object."

    Design: Corner/entities/list_customers_pagination_envelope_fields_present
    """
    fx.register_customer("lp1@x.com", ship_state_code="CA")
    fx.register_customer("lp2@x.com", ship_state_code="TX")

    resp = api_client.list_customers(ADMIN, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True


def test_list_customers_invalid_pagination_rejected(api):
    """PRD §2.3: "A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/entities/list_customers_invalid_pagination_returns_error
    """
    resp = api_client.list_customers(ADMIN, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)


def test_duplicate_sku_rejected(api):
    """PRD §3.1: "a `sku` (a catalog code that must be unique across all products)"
    PRD §2.10: "the uniqueness constraints (the `(product_id, vintage_year)` pair, `sku`, `email`, at most one active shipment per order) — surface as `ERR_INVALID_REQUEST` (HTTP 400)"

    Design: Corner/entities/duplicate_sku_returns_invalid_request
    """
    fx.create_product("DUP-1", category="WINE")
    resp = api_client.create_product(
        {"sku": "DUP-1", "name": "B", "category": "WINE", "container_type": "BOTTLE",
         "bottle_volume_ml": 750, "abv_pct": 12.00}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_duplicate_vintage_year_per_product_rejected(api):
    """PRD §3.1: "a `vintage_year` (an integer from 1900 to 2100 inclusive, unique within the product so that the `product_id` and `vintage_year` pair is unique)"

    Design: Corner/entities/duplicate_vintage_year_per_product_returns_invalid_request
    """
    product = fx.create_product("VY-1", category="WINE")
    fx.create_vintage(product["id"], vintage_year=2020, list_price_cents=3000, case_pack_size=6)
    resp = api_client.create_vintage(
        product["id"], {"vintage_year": 2020, "list_price_cents": 3500, "case_pack_size": 6}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── Corner: endpoints ──────────────────────────────────────────────────────
def test_duplicate_active_shipment_conflict(api):
    """PRD §3.10: "At most one non-cancelled shipment may exist per order; a second is rejected with `ERR_DUPLICATE_ACTIVE_SHIPMENT` (HTTP 409)."

    Design: Corner/endpoints/duplicate_active_shipment_returns_conflict
    """
    fx.set_clock()
    fx.create_state_rule("TX", ship_allowed=True, growler_keg_allowed=True,
                         requires_adult_signature=False)
    cust = fx.create_verified_customer("ds1@x.com", ship_state_code="TX")
    _, vint, _ = fx.setup_released_vintage("DS-1", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=10, vintage_year=2020)
    order = fx.build_ready_order(cust, vint["id"], 2, channel="DELIVERY", dest_state_code="TX")
    get_success_data(api_client.create_shipment(order["id"], {"carrier": "LICENSED_COMMON_CARRIER"}, ASSOCIATE))

    resp = api_client.create_shipment(order["id"], {"carrier": "STORE_COURIER"}, ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_SHIPMENT.value)


def test_shipment_on_pos_order_channel_invalid(api):
    """PRD §3.10: "Creating a shipment for a `POS` or `PICKUP` order, or for an order not in `READY` fulfillment and `CAPTURED` payment, is rejected with `ERR_SHIPMENT_CHANNEL_INVALID` (HTTP 422)."

    Design: Corner/endpoints/shipment_on_pos_order_channel_invalid
    """
    fx.set_clock()
    cust = fx.create_verified_customer("ci3@x.com", ship_state_code="CA")
    _, vint, _ = fx.setup_released_vintage("CI3-1", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=10, vintage_year=2020)
    order = fx.build_ready_order(cust, vint["id"], 2, channel="POS")

    resp = api_client.create_shipment(order["id"], {"carrier": "STORE_COURIER"}, ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_CHANNEL_INVALID.value)


def test_order_lines_filtered_by_vintage(api):
    """PRD §4: "| GET | `/order-lines` | List order lines filtered by vintage or lot | StoreAssociate, ComplianceOfficer, Admin |"
    PRD §3.3: "Cart contents are **OrderLine** rows. A line is added to a `CART` order with the `vintage_id` being purchased"

    Design: Corner/endpoints/order_lines_filtered_by_vintage_fk_reverse
    """
    fx.set_clock()
    cust = fx.create_verified_customer("ol1@x.com", ship_state_code="CA")
    _, vint, _ = fx.setup_released_vintage("OL-1", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=10, vintage_year=2020)
    order = fx.create_cart_order(cust, channel="POS")
    fx.add_line(cust, order["id"], vint["id"], 2)

    resp = api_client.list_order_lines_filtered(ASSOCIATE, params={"vintage_id": vint["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"exactly one line references the vintage, got {meta['total_count']}"


# ─── Corner: errors (non-stub) ──────────────────────────────────────────────
def test_occ_stale_order_version_on_submit(api):
    """PRD §2.9: "if `expected_order_version` does not equal the target order's current `version`, the submit is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), and no reservation or pricing side effect occurs."
    PRD §2.9: "Because every cart mutation — adding a line, removing a line — legitimately increments the order's `version`"

    Design: Corner/errors/occ_stale_order_version_on_submit
    """
    fx.set_clock()
    cust = fx.create_verified_customer("oc1@x.com", ship_state_code="CA")
    _, vint, _ = fx.setup_released_vintage("OC-1", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=10, vintage_year=2020)
    cust_h = make_customer_headers(cust["id"])
    order = get_success_data(api_client.create_order(
        {"customer_id": cust["id"], "channel": "POS"}, cust_h))
    ver0 = order["version"]
    fx.add_line(cust, order["id"], vint["id"], 2)  # bumps version past ver0

    resp = api_client.submit_order(order["id"], {"expected_order_version": ver0}, cust_h)
    validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION.value)


def test_duplicate_membership_conflict(api):
    """PRD §3.8: "A customer may hold at most one membership that is `ACTIVE` or `SUSPENDED` at a time; enrolling a customer who already has such a membership is rejected with `ERR_DUPLICATE_MEMBERSHIP` (HTTP 409)."

    Design: Corner/errors/duplicate_membership_returns_conflict
    """
    cust = fx.register_customer("dm1@x.com", ship_state_code="CA")
    cust_h = make_customer_headers(cust["id"])
    get_success_data(api_client.create_membership({"customer_id": cust["id"]}, cust_h))

    resp = api_client.create_membership({"customer_id": cust["id"]}, cust_h)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_MEMBERSHIP.value)


# ─── Corner: rbac ───────────────────────────────────────────────────────────
def test_customer_cannot_capture_payment(api):
    """PRD §2.1: "Once authentication succeeds, the system checks whether the acting role is permitted to perform the requested operation; a role acting outside its authority is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "| POST | `/orders/{id}/capture-payment` | Capture payment and withdraw bonded stock | StoreAssociate |"

    Design: Corner/rbac/customer_cannot_capture_payment_forbidden
    """
    fx.set_clock()
    cust = fx.create_verified_customer("rb1@x.com", ship_state_code="CA")
    _, vint, _ = fx.setup_released_vintage("RB-1", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=5, vintage_year=2020)
    order = fx.build_submitted_order(cust, vint["id"], 1, channel="POS")
    fx.authorize(cust, order["id"])

    resp = api_client.capture_payment(order["id"], make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_store_associate_cannot_refund(api):
    """PRD §4: "| POST | `/orders/{id}/refund` | Refund a captured order | ComplianceOfficer |"
    PRD §2.1: "a role acting outside its authority is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/store_associate_cannot_refund_forbidden
    """
    fx.set_clock()
    cust = fx.create_verified_customer("rb2@x.com", ship_state_code="CA")
    _, vint, _ = fx.setup_released_vintage("RB-2", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=5, vintage_year=2020)
    order = fx.build_captured_order(cust, vint["id"], 1, channel="POS")

    resp = api_client.refund_order(order["id"], ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` names a role the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api_client._request("GET", "/orders", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_customer_cannot_act_on_other_customers_order(api):
    """PRD §2.1: "Ownership checks on any resource that references a `Customer` — an order ... compare that resource's customer foreign key (directly or through its parent) to `X-User-ID`. A `Customer` attempting to act on a resource owned by a different customer is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/customer_cannot_act_on_other_customers_order_forbidden
    """
    cust_a = fx.register_customer("own-a@x.com", ship_state_code="CA")
    cust_b = fx.register_customer("own-b@x.com", ship_state_code="CA")
    order = fx.create_cart_order(cust_a, channel="POS")

    resp = api_client.cancel_order(order["id"], make_customer_headers(cust_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
