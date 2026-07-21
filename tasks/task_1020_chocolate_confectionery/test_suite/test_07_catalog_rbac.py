"""Catalog defaults, bundles, not-found, auth, and ownership (PRD §2.1, §2.4, §3.1, §3.5).

Covers server-applied product/customer defaults, bundle reverse-listing and
self-reference rejection, missing-auth rejection, terminal-state re-cancel, and
cross-customer ownership enforcement.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    make_customer_headers, ADMIN, bundle_component_payload,
    create_customer, create_product, create_order,
)


def test_create_product_minimal_applies_defaults(api):
    """PRD §3.1: "A product may optionally set `requires_tempering`, which
    defaults to false". PRD §3.1: "a `status` that is `ACTIVE` on creation". PRD
    §2.4: "`version` is an integer that begins at 1 on creation".

    Design: Corner/entities/create_product_minimal_applies_defaults
    """
    product = create_product()  # minimal: no status / requires_tempering supplied
    fetched = validate_success(api.get_product(product["id"], ADMIN))
    assert fetched["status"] == "ACTIVE", fetched
    assert fetched["requires_tempering"] is False, fetched
    assert fetched["version"] == 1, fetched


def test_create_customer_wallet_defaults_zero(api):
    """PRD §3.2: "Each customer also carries a store-credit balance,
    `wallet_credit_cents`, which begins at 0 and is a system-maintained field."

    Design: Corner/entities/create_customer_wallet_defaults_zero
    """
    customer = create_customer(account_type="RETAIL")
    fetched = validate_success(api.get_customer(customer["id"], ADMIN))
    assert fetched["wallet_credit_cents"] == 0, fetched


def test_get_product_not_found(api):
    """PRD §2.5: "The concrete not-found identifiers are ... `ERR_PRODUCT_NOT_FOUND`".

    Design: Corner/entities/get_product_not_found
    """
    resp = api.get_product(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, "ERR_PRODUCT_NOT_FOUND", 404)


def test_bundle_component_reverse_reachable_filtered_list(api):
    """PRD §3.1: "Components may later be listed or filtered by their
    `bundle_product_id` or `component_product_id`." PRD §3.1: "Adding a component
    to a bundle takes a `component_product_id` and a `quantity` — the number of
    units of that component contained in one bundle unit."

    Design: Corner/entities/bundle_component_reverse_reachable_filtered_list
    """
    bundle = create_product(product_type="BUNDLE", base_price_cents=3000, unit_weight_g=300)
    component = create_product(product_type="SINGLE", base_price_cents=400, unit_weight_g=15)
    validate_success(
        api.add_bundle_component(bundle["id"], bundle_component_payload(component["id"], 6), ADMIN),
        201,
    )
    data, _meta = validate_paginated(
        api.list_bundle_components(ADMIN, params={"bundle_product_id": bundle["id"]}))
    assert len(data) == 1, data
    assert data[0]["component_product_id"] == component["id"], data[0]
    assert data[0]["quantity"] == 6, data[0]


def test_bundle_component_self_reference_rejected(api):
    """PRD §3.1: "A component attachment is only valid when the parent product it
    is attached to is of type `BUNDLE`, the referenced component product is of
    type `SINGLE`, the component is not the bundle itself, and the `quantity` is
    greater than zero; any violation is rejected with
    `ERR_BUNDLE_COMPONENT_INVALID`."

    Design: Corner/validations/bundle_component_self_reference_rejected
    """
    bundle = create_product(product_type="BUNDLE", base_price_cents=3000, unit_weight_g=200)
    resp = api.add_bundle_component(
        bundle["id"], bundle_component_payload(bundle["id"], 1), ADMIN)
    validate_error(resp, "ERR_BUNDLE_COMPONENT_INVALID", 422)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing or malformed, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing."

    Design: Corner/errors/missing_auth_headers_returns_unauthenticated
    """
    product = create_product()
    resp = api.get_product(product["id"], headers=None)
    validate_error(resp, "ERR_UNAUTHENTICATED", 401)


def test_cancel_already_cancelled_order_invalid_state(api):
    """PRD §2.5: "state legality of the requested transition (`ERR_INVALID_STATE`)".
    PRD §3.6: "A `DRAFT` order simply becomes `CANCELLED`." Re-cancelling a
    terminal CANCELLED order is not a defined transition.

    Design: Corner/state_machines/cancel_already_cancelled_order_invalid_state
    """
    customer = create_customer(account_type="RETAIL")
    order = create_order(customer["id"], "RETAIL")
    headers = make_customer_headers(customer["id"])
    validate_success(api.cancel_order(order["id"], headers))
    resp = api.cancel_order(order["id"], headers)
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_customer_cannot_cancel_others_order(api):
    """PRD §2.1: "a `Customer` may only act on an `Order`, `CustomOrder`, or
    `Subscription` whose `customer_id` equals their own `X-User-ID`; a mismatch
    is rejected with `ERR_OWNERSHIP_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_cancel_others_order
    """
    owner = create_customer(account_type="RETAIL")
    other = create_customer(account_type="RETAIL")
    order = create_order(owner["id"], "RETAIL")
    resp = api.cancel_order(order["id"], make_customer_headers(other["id"]))
    validate_error(resp, "ERR_OWNERSHIP_FORBIDDEN", 403)
