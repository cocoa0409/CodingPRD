"""
Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce clear
"Setup failed" errors instead of confusing assertion failures.

IDENTITY THREADING: a Customer is entity_backed. After a customer is created, every
ownership-gated call on that customer's resources (order create/lines/place/cancel,
subscription pay/cancel, challenge start-round) MUST use make_customer_headers(customer["id"]).
The shared TEST_USERS["customer_headers"] constant is only for non-ownership Customer tests.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_store_payload, create_menu_item_payload, create_modifier_payload,
    create_pickup_slot_payload, create_customer_payload, create_subscription_plan_payload,
    create_subscription_payload, create_order_payload, create_order_line_payload,
    create_loyalty_challenge_payload, wallet_adjustment_payload, points_ledger_payload,
)
from .test_users import (
    TEST_USERS, make_customer_headers, make_store_manager_headers, make_platform_admin_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]


# ─── Clock control ───────────────────────────────────────────

def set_clock(iso8601: str):
    """Set the logical clock to a supplied instant (admin-only)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, ADMIN))


# ─── Tier 1/2: Primitive creation ────────────────────────────

def create_store(**overrides):
    """Create a store (public bootstrap)."""
    return get_success_data(api_client.create_store(create_store_payload(**overrides), ADMIN))


def create_menu_item(store_id, **overrides):
    return get_success_data(
        api_client.create_menu_item(create_menu_item_payload(store_id, **overrides), ADMIN)
    )


def create_modifier(menu_item_id, **overrides):
    return get_success_data(
        api_client.create_modifier(create_modifier_payload(menu_item_id, **overrides), ADMIN)
    )


def create_pickup_slot(store_id, **overrides):
    return get_success_data(
        api_client.create_pickup_slot(create_pickup_slot_payload(store_id, **overrides), ADMIN)
    )


def create_customer(home_store_id, **overrides):
    """Create a customer (public bootstrap). Returns the customer dict (carries
    loyalty_account_id)."""
    return get_success_data(
        api_client.create_customer(create_customer_payload(home_store_id, **overrides),
                                   TEST_USERS["customer_headers"])
    )


def create_subscription_plan(**overrides):
    return get_success_data(
        api_client.create_subscription_plan(create_subscription_plan_payload(**overrides), ADMIN)
    )


def seed_wallet(customer_id, delta_cents, reason="SEED"):
    """Operator wallet credit. Returns the updated customer."""
    return get_success_data(
        api_client.adjust_wallet(customer_id, wallet_adjustment_payload(delta_cents, reason), ADMIN)
    )


def seed_points(loyalty_account_id, delta_points, reason="ADJUSTMENT"):
    """Operator points adjustment (ADJUSTMENT). Returns the ledger entry."""
    return get_success_data(
        api_client.create_points_ledger_entry(
            points_ledger_payload(loyalty_account_id, delta_points, reason), ADMIN
        )
    )


# ─── Tier 2: Active subscription ─────────────────────────────

def create_active_subscription(customer_id, plan_id):
    """Create a subscription and pay it to ACTIVE. Returns the active subscription."""
    sub = get_success_data(
        api_client.create_subscription(
            create_subscription_payload(customer_id, plan_id), make_customer_headers(customer_id)
        )
    )
    paid = get_success_data(
        api_client.pay_subscription(
            sub["id"], {"payment_outcome": "SUCCEEDED"}, make_customer_headers(customer_id)
        )
    )
    return paid


# ─── Tier 2: Base ordering setup ─────────────────────────────

def setup_store_item_slot_customer(store_overrides=None, item_overrides=None,
                                   slot_overrides=None, customer_overrides=None):
    """Active store + one menu item + one slot + one customer.
    Returns (store, item, slot, customer)."""
    store = create_store(**(store_overrides or {}))
    item = create_menu_item(store["id"], **(item_overrides or {}))
    slot = create_pickup_slot(store["id"], **(slot_overrides or {}))
    customer = create_customer(store["id"], **(customer_overrides or {}))
    return store, item, slot, customer


# ─── Tier 3: Order lifecycle shortcuts ───────────────────────

def create_cart_order(customer_id, store_id, slot_id, subscription_id=None):
    """Open a CART order for a customer. Returns the order."""
    payload = create_order_payload(customer_id, store_id, slot_id)
    if subscription_id is not None:
        payload["subscription_id"] = subscription_id
    return get_success_data(
        api_client.create_order(payload, make_customer_headers(customer_id))
    )


def add_line(customer_id, order_id, menu_item_id, quantity=1, modifier_ids=None):
    """Add a line to a CART order owned by customer_id. Returns the order line."""
    payload = create_order_line_payload(menu_item_id, quantity)
    if modifier_ids is not None:
        payload["modifier_ids"] = modifier_ids
    return get_success_data(
        api_client.add_order_line(order_id, payload, make_customer_headers(customer_id))
    )


def place(customer_id, order_id, expected_slot_version, points_redeemed=0):
    """Place a CART order. Returns the placed order (carries new slot/pricing state)."""
    return get_success_data(
        api_client.place_order(
            order_id,
            {"points_redeemed": points_redeemed,
             "expected_pickup_slot_version": expected_slot_version},
            make_customer_headers(customer_id),
        )
    )


def create_and_place_order(customer_id, store_id, slot_id, menu_item_id,
                           slot_version, quantity=1, points_redeemed=0,
                           subscription_id=None, modifier_ids=None):
    """Open cart -> add one line -> place. Returns (order, new_slot_version)."""
    order = create_cart_order(customer_id, store_id, slot_id, subscription_id=subscription_id)
    add_line(customer_id, order["id"], menu_item_id, quantity=quantity, modifier_ids=modifier_ids)
    placed = place(customer_id, order["id"], slot_version, points_redeemed=points_redeemed)
    # Placement bumps the slot's version by one (PRD §3.5). The placed-order response does
    # not carry the slot version, so re-read the slot to return its current version.
    new_slot_version = get_slot(slot_id)["version"]
    return placed, new_slot_version


def advance(order_id):
    """StoreManager advance one kitchen step."""
    return get_success_data(api_client.advance_order(order_id, MANAGER))


def complete(order_id):
    """StoreManager complete a READY order. Returns the completed order."""
    return get_success_data(api_client.complete_order(order_id, MANAGER))


def create_completed_order(customer_id, store_id, slot_id, menu_item_id,
                           slot_version, quantity=1, points_redeemed=0,
                           subscription_id=None):
    """Open cart -> line -> place -> advance x2 -> complete.
    Returns (completed_order, new_slot_version)."""
    placed, new_v = create_and_place_order(
        customer_id, store_id, slot_id, menu_item_id, slot_version,
        quantity=quantity, points_redeemed=points_redeemed, subscription_id=subscription_id,
    )
    advance(placed["id"])
    advance(placed["id"])
    done = complete(placed["id"])
    return done, new_v


def make_it_right(order_id, refund_amount_cents, refund_destination):
    """StoreManager make-it-right refund. Returns the order."""
    return get_success_data(
        api_client.make_it_right(
            order_id,
            {"refund_amount_cents": refund_amount_cents, "refund_destination": refund_destination},
            MANAGER,
        )
    )


def cancel(customer_id, order_id, refund_destination="ORIGINAL"):
    """Customer cancel order. Returns the order."""
    return get_success_data(
        api_client.cancel_order(
            order_id, {"refund_destination": refund_destination},
            make_customer_headers(customer_id),
        )
    )


# ─── Tier 4: Slot saturation / accumulation ──────────────────

def saturate_slot(store_id, menu_item_id, slot_id, count):
    """Use the test-driving inject endpoint to place `count` orders against a slot.
    Returns the slot dict after saturation."""
    return get_success_data(
        api_client.inject_place_n_orders(
            {"store_id": store_id, "menu_item_id": menu_item_id,
             "pickup_slot_id": slot_id, "count": count},
            ADMIN,
        )
    )


# ─── Read helpers ────────────────────────────────────────────

def get_order(order_id, headers=None):
    return get_success_data(api_client.get_order(order_id, headers or ADMIN))


def get_slot(slot_id, headers=None):
    return get_success_data(api_client.get_pickup_slot(slot_id, headers or ADMIN))


def get_store(store_id, headers=None):
    return get_success_data(api_client.get_store(store_id, headers or ADMIN))


def get_customer(customer_id, headers=None):
    return get_success_data(api_client.get_customer(customer_id, headers or ADMIN))


def get_loyalty_account(account_id, headers=None):
    return get_success_data(api_client.get_loyalty_account(account_id, headers or ADMIN))


def get_subscription(subscription_id, headers=None):
    return get_success_data(api_client.get_subscription(subscription_id, headers or ADMIN))


def get_challenge(challenge_id, headers=None):
    return get_success_data(api_client.get_loyalty_challenge(challenge_id, headers or ADMIN))


def get_order_line(line_id, headers=None):
    return get_success_data(api_client.get_order_line(line_id, headers or ADMIN))
