"""Resource creation defaults, not-found and validation errors, registry
closure and listing, and role/ownership access control."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    new_store, new_product, new_member, new_registry, close_registry,
    api_client, TEST_USERS, make_customer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
MERCH = TEST_USERS["merch_headers"]


# ─── create_store_returns_201_with_fields (queue B) ───

def test_create_store_returns_201_and_version_one():
    """PRD §4: "Operations that create a new stand-alone resource or add a new
    resource to a collection return `201 Created`."
    PRD §2.4: "`version`: an integer that starts at 1 on creation and increments by
    1 on every mutation."

    Design: Corner/entities/create_store_returns_201_with_fields
    """
    resp = api_client.create_store(
        {"name": "Store E1", "region_code": "CA", "oversized_slots_per_day": 3}, ADMIN)
    data = validate_success(resp, 201)
    assert data["version"] == 1, f"expected version 1, got {data['version']}"
    assert data["oversized_slots_per_day"] == 3, (
        f"expected oversized_slots_per_day 3, got {data['oversized_slots_per_day']}")


# ─── get_store_not_found_returns_404 (queue B) ───

def test_get_missing_store_returns_not_found():
    """PRD §2.9: "When an endpoint path names a resource by its identifier, the
    system validates existence left-to-right and returns the first applicable
    not-found error before evaluating any further rule."

    Design: Corner/entities/get_store_not_found_returns_404
    """
    resp = api_client.get_store("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(resp, ApiErrorId.ERR_STORE_NOT_FOUND.value)


# ─── create_product_missing_required_field_returns_validation (queue B) ───

def test_create_product_missing_base_price_rejected():
    """PRD §2.1: "Structurally malformed bodies — missing required fields, bad enum
    values, or a negative or zero value where a positive one is required — are
    rejected with `ERR_VALIDATION`."

    Design: Corner/entities/create_product_missing_required_field_returns_validation
    """
    resp = api_client.create_product(
        {"sku": "SKU-BAD", "name": "No Price", "category": "DECOR",
         "clearance_floor_cents": 100, "first_received_at": "2026-06-25T00:00:00Z"}, MERCH)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ─── add_item_to_closed_registry_returns_registry_closed (queue B) ───

def test_add_item_to_closed_registry_rejected():
    """PRD §3.8: "Items may be added only while the registry is `ACTIVE`; adding to a
    `CLOSED` registry is rejected with `ERR_REGISTRY_CLOSED`."

    Design: Corner/state_machines/add_item_to_closed_registry_returns_registry_closed
    """
    product = new_product(sku="SKU-SM6", name="Sconce", category="DECOR",
                          base_price_cents=2500, clearance_floor_cents=200,
                          first_received_at="2026-06-25T00:00:00Z")
    member = new_member(email="sm6@x.com", full_name="SM Six")
    registry = new_registry(member["id"], title="Wedding", event_date="2026-11-01")
    close_registry(registry["id"], member["id"])
    resp = api_client.add_registry_item(
        registry["id"], {"product_id": product["id"], "desired_qty": 1},
        make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_REGISTRY_CLOSED.value)


# ─── list_registries_by_owner_reverse_reachability (queue B) ───

def test_list_registries_filtered_by_owner():
    """PRD §2.9: "Listing endpoints accept optional foreign-key filters that narrow
    the collection by reverse-reachability: ... registries by `owner_member_id`".
    PRD §2.3: "Each list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_registries_by_owner_reverse_reachability
    """
    member = new_member(email="ep3@x.com", full_name="EP Three")
    registry = new_registry(member["id"], title="New Home", event_date="2026-10-01")
    resp = api_client.list_registries(
        make_customer_headers(member["id"]), params={"owner_member_id": member["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 1, f"expected >= 1 registry, got {meta['total_count']}"
    assert any(r["id"] == registry["id"] for r in data), "owner's registry missing from listing"


# ─── redeem_points_exceeds_balance_rejected (queue B) ───

def test_redeem_more_points_than_balance_rejected():
    """PRD §3.4: "The `redeemed_cents` on the order equals the
    `requested_redeem_points` (one point per cent), which is validated at creation
    against the member's available `points_balance`; a request to redeem more than
    the member holds is rejected with `ERR_INSUFFICIENT_POINTS`."

    Design: Corner/validations/redeem_points_exceeds_balance_rejected
    """
    store = new_store(name="Store V6")
    member = new_member(email="v6@x.com", full_name="V Six", initial_points_balance=100)
    resp = api_client.create_order(
        {"store_id": store["id"], "order_type": "CARRYOUT",
         "member_id": member["id"], "requested_redeem_points": 500}, TEST_USERS["associate_headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)


# ─── customer_cannot_create_product_unauthorized (queue B) ───

def test_customer_cannot_create_product():
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/customer_cannot_create_product_unauthorized
    """
    member = new_member(email="rb1@x.com", full_name="RB One")
    resp = api_client.create_product(
        {"sku": "SKU-RB1", "name": "Hijack", "category": "DECOR",
         "base_price_cents": 1000, "clearance_floor_cents": 100,
         "first_received_at": "2026-06-25T00:00:00Z"}, make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ─── customer_cannot_close_another_members_registry (queue B) ───

def test_customer_cannot_close_registry_they_do_not_own():
    """PRD §3.8: "Because the `Customer` role is entity-backed, the acting user may
    only act on registries whose `owner_member_id` matches their own `X-User-ID`, and
    an attempt to act on someone else's registry is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/customer_cannot_close_another_members_registry
    """
    member_a = new_member(email="rb2a@x.com", full_name="RB Two A")
    member_b = new_member(email="rb2b@x.com", full_name="RB Two B")
    registry = new_registry(member_a["id"], title="A's Registry", event_date="2026-10-01")
    resp = api_client.close_registry(registry["id"], make_customer_headers(member_b["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ─── get_store_missing_headers_rejected (queue B) ───

def test_missing_user_context_headers_rejected():
    """PRD §2.1: "A request that omits either header, or that carries a role string
    the system does not recognise, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/get_store_missing_headers_rejected
    """
    store = new_store(name="Store RB3")
    resp = api_client.get_store(store["id"], {})  # no X-User-ID / X-User-Role
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)
