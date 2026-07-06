"""CRUD, defaults, computed fields, invalid transitions, line validation, RBAC, listing."""
from test_helpers import (
    setup_store_item_slot_customer, create_store, create_menu_item, create_modifier,
    create_pickup_slot, create_customer, create_subscription_plan, create_cart_order,
    add_line, create_and_place_order, advance, seed_points, make_customer_headers,
    create_subscription_payload, create_loyalty_challenge_payload,
    validate_error, validate_success, validate_paginated, NON_EXISTENT_UUID,
    api_client, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
CUSTOMER = TEST_USERS["customer_headers"]


# ─── entities section ───

def test_create_store_returns_201_with_queue_open(api):
    """PRD §3.1: "The store's `queue_status` is computed, never supplied, and starts at `OPEN`."
    PRD §2.4: "`version` (integer): a system-managed integer that starts at its initial value on
    creation".

    Design: Corner/entities/create_store_returns_201_with_queue_open
    """
    res = api.create_store(
        {"name": "S", "state_code": "CA", "throughput_capacity_per_slot": 5, "locker_count": 2},
        ADMIN)
    store = validate_success(res, 201)
    assert store["queue_status"] == "OPEN"
    assert store["version"] == 1


def test_get_store_not_found(api):
    """PRD §2.5: "If any path identifier or any referenced resource — a store, menu item,
    modifier, pickup slot, customer, order, subscription, or any other addressed entity — does
    not exist, the request is rejected with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_store_not_found
    """
    res = api.get_store("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_menu_item_missing_required_field(api):
    """PRD §3.11: "Request well-formedness comes fourth: a missing required body field, a wrong
    type, or an enum value outside its declared set yields `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_menu_item_missing_required_field
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=5)
    res = api.create_menu_item(
        {"store_id": store["id"], "name": "X", "base_calories": 100}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_menu_item_allergen_tags_default_empty(api):
    """PRD §3.1: "an `allergen_tags` array (defaulting to empty) drawn from the recognized
    allergen vocabulary".

    Design: Corner/entities/menu_item_allergen_tags_default_empty
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=5)
    res = api.create_menu_item(
        {"store_id": store["id"], "name": "X", "base_price_cents": 500, "base_calories": 100},
        ADMIN)
    item = validate_success(res, 201)
    assert item["allergen_tags"] == []


def test_order_line_effective_allergens_computed_union(api):
    """PRD §2.9: "The effective allergens of an order line are the union of the item's allergens
    and the allergens added by every modifier applied to that line."

    Design: Corner/entities/order_line_effective_allergens_computed_union
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=5)
    item = create_menu_item(store["id"], name="X", base_price_cents=500, base_calories=100,
                            allergen_tags=["DAIRY"])
    modifier = create_modifier(item["id"], name="AddNuts", price_delta_cents=50,
                               calorie_delta=20, adds_allergen_tags=["NUTS"])
    slot = create_pickup_slot(store["id"])
    customer = create_customer(store["id"])

    order = create_cart_order(customer["id"], store["id"], slot["id"])
    line = add_line(customer["id"], order["id"], item["id"], quantity=1,
                    modifier_ids=[modifier["id"]])

    tags = line["effective_allergen_tags"]
    assert "DAIRY" in tags and "NUTS" in tags


def test_duplicate_customer_email_rejected(api):
    """PRD §3.3: "Registering with an `email` already in use is rejected with
    `ERR_DUPLICATE_EMAIL`."

    Design: Corner/entities/duplicate_customer_email_rejected
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=5)
    validate_success(
        api.create_customer(
            {"email": "dup@x.com", "full_name": "D1", "home_store_id": store["id"]}, CUSTOMER), 201)
    res = api.create_customer(
        {"email": "dup@x.com", "full_name": "D2", "home_store_id": store["id"]}, CUSTOMER)
    validate_error(res, "ERR_DUPLICATE_EMAIL")


def test_ledger_entry_immutable_no_version(api):
    """PRD §2.4: "a `PointsLedgerEntry` is an immutable, append-only audit record. It carries
    only `id` (UUID) and `created_at`; it has no `updated_at` and no `version`, because once
    written a ledger entry is never modified."

    Design: Corner/entities/ledger_entry_immutable_no_version
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=5)
    customer = create_customer(store["id"])
    seed_points(customer["loyalty_account_id"], 100)

    data, meta = validate_paginated(
        api.list_points_ledger_entries(
            ADMIN, params={"loyalty_account_id": customer["loyalty_account_id"]}))
    assert len(data) >= 1
    for entry in data:
        assert "version" not in entry, "append-only ledger entry must not carry version"


# ─── state_machines section ───

def test_advance_cart_order_returns_invalid_state(api):
    """PRD §3.6: "Each advance is only valid from its named source state, and any attempt to
    advance from another state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/advance_cart_order_returns_invalid_state
    """
    store, item, slot, customer = setup_store_item_slot_customer(
        item_overrides={"base_price_cents": 500, "base_calories": 100})
    order = create_cart_order(customer["id"], store["id"], slot["id"])
    add_line(customer["id"], order["id"], item["id"], quantity=1)

    res = api.advance_order(order["id"], MANAGER)
    validate_error(res, "ERR_INVALID_STATE")


def test_complete_completed_order_terminal_lockdown(api):
    """PRD §3.6: "Each advance is only valid from its named source state, and any attempt to
    advance from another state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/complete_completed_order_terminal_lockdown
    """
    store, item, slot, customer = setup_store_item_slot_customer(
        item_overrides={"base_price_cents": 500, "base_calories": 100})
    placed, _ = create_and_place_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"], quantity=1)
    advance(placed["id"])
    advance(placed["id"])
    validate_success(api.complete_order(placed["id"], MANAGER), 200)

    res = api.complete_order(placed["id"], MANAGER)
    validate_error(res, "ERR_INVALID_STATE")


def test_challenge_start_round_when_in_progress_rejected(api):
    """PRD §3.10: "starting a round on a challenge not in `ROUND_COMPLETE` is rejected with
    `ERR_CHALLENGE_NOT_READY`."

    Design: Corner/state_machines/challenge_start_round_when_in_progress_rejected
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=5)
    customer = create_customer(store["id"])
    challenge = validate_success(
        api.create_loyalty_challenge(
            create_loyalty_challenge_payload(customer["id"], target_order_count=3, bonus_points=500),
            make_customer_headers(customer["id"])), 201)

    res = api.start_challenge_round(challenge["id"], make_customer_headers(customer["id"]))
    validate_error(res, "ERR_CHALLENGE_NOT_READY")


# ─── validations section ───

def test_modifier_mismatch_wrong_menu_item(api):
    """PRD §3.11: "when adding or updating an order line, each modifier named in `modifier_ids`
    must belong to that line's `menu_item_id`, and the menu item must belong to the order's
    `store_id`, or the request is rejected with `ERR_MODIFIER_MISMATCH`."

    Design: Corner/validations/modifier_mismatch_wrong_menu_item
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=5)
    item_a = create_menu_item(store["id"], name="A", base_price_cents=500, base_calories=100)
    item_b = create_menu_item(store["id"], name="B", base_price_cents=700, base_calories=200)
    bmod = create_modifier(item_b["id"], name="BMod", price_delta_cents=50, calorie_delta=10)
    slot = create_pickup_slot(store["id"])
    customer = create_customer(store["id"])

    order = create_cart_order(customer["id"], store["id"], slot["id"])
    res = api.add_order_line(
        order["id"], {"menu_item_id": item_a["id"], "quantity": 1, "modifier_ids": [bmod["id"]]},
        make_customer_headers(customer["id"]))
    validate_error(res, "ERR_MODIFIER_MISMATCH")


def test_item_unavailable_line_rejected(api):
    """PRD §3.4: "Adding a line for a menu item whose `is_available` is false, or whose store is
    not active, is rejected with `ERR_ITEM_UNAVAILABLE`."

    Design: Corner/validations/item_unavailable_line_rejected
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=5)
    item = create_menu_item(store["id"], name="X", base_price_cents=500, base_calories=100,
                            is_available=False)
    slot = create_pickup_slot(store["id"])
    customer = create_customer(store["id"])

    order = create_cart_order(customer["id"], store["id"], slot["id"])
    res = api.add_order_line(
        order["id"], {"menu_item_id": item["id"], "quantity": 1},
        make_customer_headers(customer["id"]))
    validate_error(res, "ERR_ITEM_UNAVAILABLE")


def test_invalid_quantity_zero_rejected(api):
    """PRD §3.4: "A quantity below 1 is rejected with `ERR_INVALID_QUANTITY`."

    Design: Corner/validations/invalid_quantity_zero_rejected
    """
    store, item, slot, customer = setup_store_item_slot_customer(
        item_overrides={"base_price_cents": 500, "base_calories": 100})
    order = create_cart_order(customer["id"], store["id"], slot["id"])
    res = api.add_order_line(
        order["id"], {"menu_item_id": item["id"], "quantity": 0},
        make_customer_headers(customer["id"]))
    validate_error(res, "ERR_INVALID_QUANTITY")


# ─── errors section ───

def test_subscription_payment_failed(api):
    """PRD §3.9: "Payment is honored only when the outcome is `SUCCEEDED`; any other outcome is
    rejected with `ERR_PAYMENT_FAILED`."

    Design: Corner/errors/subscription_payment_failed
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=5)
    plan = create_subscription_plan(tier_name="P1", monthly_fee_cents=999)
    customer = create_customer(store["id"])
    sub = validate_success(
        api.create_subscription(
            create_subscription_payload(customer["id"], plan["id"]),
            make_customer_headers(customer["id"])), 201)

    res = api.pay_subscription(
        sub["id"], {"payment_outcome": "FAILED"}, make_customer_headers(customer["id"]))
    validate_error(res, "ERR_PAYMENT_FAILED")

    sub_after = validate_success(api.get_subscription(sub["id"], ADMIN), 200)
    assert sub_after["status"] == "PENDING_PAYMENT"


# ─── rbac section ───

def test_customer_cannot_complete_order(api):
    """PRD §2.1: "Once authenticated, a caller may only invoke endpoints their role is authorized
    for, and an entity-backed role may only act on resources it owns; a violation is rejected
    with `ERR_FORBIDDEN`."

    Design: Corner/rbac/customer_cannot_complete_order
    """
    store, item, slot, customer = setup_store_item_slot_customer(
        item_overrides={"base_price_cents": 500, "base_calories": 100})
    placed, _ = create_and_place_order(
        customer["id"], store["id"], slot["id"], item["id"], slot["version"], quantity=1)
    advance(placed["id"])
    advance(placed["id"])

    res = api.complete_order(placed["id"], make_customer_headers(customer["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_customer_cannot_place_other_customers_order(api):
    """PRD §2.1: "an entity-backed role may only act on resources it owns; a violation is
    rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/customer_cannot_place_other_customers_order
    """
    store, item, slot, _ = setup_store_item_slot_customer(
        item_overrides={"base_price_cents": 500, "base_calories": 100})
    cust_a = create_customer(store["id"])
    cust_b = create_customer(store["id"])

    order = create_cart_order(cust_a["id"], store["id"], slot["id"])
    add_line(cust_a["id"], order["id"], item["id"], quantity=1)

    res = api.place_order(
        order["id"], {"points_redeemed": 0, "expected_pickup_slot_version": slot["version"]},
        make_customer_headers(cust_b["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the known roles,
    the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=5)
    slot = create_pickup_slot(store["id"])
    customer = create_customer(store["id"])
    order = create_cart_order(customer["id"], store["id"], slot["id"])

    res = api.get_order(order["id"], {})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── endpoints section ───

def test_list_orders_filter_by_customer_reverse_reachability(api):
    """PRD §2.5: "orders by `customer_id`, `store_id`, `pickup_slot_id`, or `subscription_id`".
    PRD §2.3: "Paginated list responses include the following fields in the `meta` object of the
    response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_orders_filter_by_customer_reverse_reachability
    """
    store = create_store(state_code="TX", throughput_capacity_per_slot=5)
    slot = create_pickup_slot(store["id"])
    customer = create_customer(store["id"])
    order = create_cart_order(customer["id"], store["id"], slot["id"])

    data, meta = validate_paginated(
        api.list_orders(make_customer_headers(customer["id"]),
                        params={"customer_id": customer["id"]}))
    ids = [o["id"] for o in data]
    assert order["id"] in ids
    assert all(o["customer_id"] == customer["id"] for o in data)
    assert "total_count" in meta and "has_more" in meta
