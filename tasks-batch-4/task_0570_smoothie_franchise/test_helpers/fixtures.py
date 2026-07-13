"""Composite setup helpers.

Each test runs against a freshly restarted server with an empty database, so
every helper builds its preconditions from scratch using only PRD endpoints.
Setup calls use the lenient get_success_data() so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: after creating an entity-backed principal (Store, Customer,
Franchisee), ownership-gated calls use the per-instance header builders
(make_store_staff_headers, make_customer_headers, make_franchisee_headers) with
that entity's real id — never the shared fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import (
    TEST_USERS,
    make_franchisee_headers,
    make_store_staff_headers,
    make_customer_headers,
)
from .factories import (
    create_franchisee_payload,
    create_store_payload,
    create_delivery_vehicle_payload,
    create_ingredient_payload,
    create_inventory_lot_payload,
    create_menu_item_payload,
    create_boost_payload,
    create_customer_payload,
    create_subscription_payload,
    create_order_payload,
    order_line,
    create_reconciliation_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# --- Clock -------------------------------------------------------------------

def set_clock(api, iso: str):
    return get_success_data(api.set_clock(iso, ADMIN))


# --- Granular builders -------------------------------------------------------

def create_franchisee(api, **overrides) -> dict:
    return get_success_data(api.create_franchisee(create_franchisee_payload(**overrides), ADMIN))


def create_store(api, franchisee_id, **overrides) -> dict:
    return get_success_data(
        api.create_store(franchisee_id, create_store_payload(**overrides), ADMIN)
    )


def open_store(api, store: dict) -> dict:
    payload = {"expected_store_version": store["version"], "status": "OPEN"}
    return get_success_data(api.update_store(store["id"], payload, ADMIN))


def suspend_store(api, store: dict) -> dict:
    payload = {"expected_store_version": store["version"], "status": "SUSPENDED"}
    return get_success_data(api.update_store(store["id"], payload, ADMIN))


def create_open_store(api, franchisee=None, **store_overrides):
    """Create a franchisee (unless given), a store, and transition it to OPEN.

    Returns (franchisee, open_store)."""
    fr = franchisee or create_franchisee(api)
    store = create_store(api, fr["id"], **store_overrides)
    store = open_store(api, store)
    return fr, store


def create_ingredient(api, **overrides) -> dict:
    return get_success_data(api.create_ingredient(create_ingredient_payload(**overrides), ADMIN))


def create_inventory_lot(api, store_id, ingredient_id, **overrides) -> dict:
    payload = create_inventory_lot_payload(ingredient_id=ingredient_id, **overrides)
    return get_success_data(
        api.create_inventory_lot(store_id, payload, make_store_staff_headers(store_id))
    )


def create_menu_item(api, **overrides) -> dict:
    return get_success_data(api.create_menu_item(create_menu_item_payload(**overrides), ADMIN))


def create_boost(api, **overrides) -> dict:
    return get_success_data(api.create_boost(create_boost_payload(**overrides), ADMIN))


def create_customer(api, **overrides) -> dict:
    return get_success_data(api.create_customer(create_customer_payload(**overrides), ANON))


def create_subscription(api, customer_id, **overrides) -> dict:
    payload = create_subscription_payload(**overrides)
    return get_success_data(
        api.create_subscription(customer_id, payload, make_customer_headers(customer_id))
    )


def renew_subscription(api, subscription_id, outcome) -> dict:
    return get_success_data(
        api.renew_subscription(subscription_id, {"payment_outcome": outcome}, ADMIN)
    )


def create_delivery_vehicle(api, store_id, franchisee_id, **overrides) -> dict:
    payload = create_delivery_vehicle_payload(**overrides)
    return get_success_data(
        api.create_delivery_vehicle(store_id, payload, make_franchisee_headers(franchisee_id))
    )


def set_vehicle_maintenance(api, vehicle_id, franchisee_id) -> dict:
    return get_success_data(
        api.update_delivery_vehicle(vehicle_id, {"status": "MAINTENANCE"},
                                    make_franchisee_headers(franchisee_id))
    )


# --- Order lifecycle helpers -------------------------------------------------

def place_order(api, store_id, customer_id, lines, **order_overrides) -> dict:
    payload = create_order_payload(store_id, lines, **order_overrides)
    return get_success_data(api.create_order(payload, make_customer_headers(customer_id)))


def pay_order(api, order_id, customer_id) -> dict:
    return get_success_data(api.pay_order(order_id, make_customer_headers(customer_id)))


def advance_order_to_completed(api, order_id, customer_id, store_id) -> dict:
    """pay -> ready -> complete. Returns the completed (PICKED_UP) order."""
    pay_order(api, order_id, customer_id)
    get_success_data(api.ready_order(order_id, make_store_staff_headers(store_id)))
    return get_success_data(api.complete_order(order_id, make_store_staff_headers(store_id)))


# --- Standard order-ready environment ---------------------------------------

def setup_order_env(api, *, menu=None, ingredient=None, lot=None, customer=None, store=None):
    """OPEN store + one ingredient + one AVAILABLE lot + one SMOOTHIE menu item +
    one customer. Every leg accepts overrides so callers can pin exact values.

    Returns a dict with keys: franchisee, store, ingredient, lot, menu_item, customer.
    """
    fr, st = create_open_store(api, **(store or {}))
    ing = create_ingredient(api, **(ingredient or {}))
    lot_overrides = dict(lot or {})
    lot_row = create_inventory_lot(api, st["id"], ing["id"], **lot_overrides)
    menu_overrides = dict(menu or {})
    if "recipe" not in menu_overrides:
        menu_overrides["recipe"] = [{"ingredient_id": ing["id"], "base_qty": 50}]
    else:
        # Substitute the ingredient id into recipe entries lacking one.
        for entry in menu_overrides["recipe"]:
            entry.setdefault("ingredient_id", ing["id"])
    mi = create_menu_item(api, **menu_overrides)
    cust = create_customer(api, **(customer or {}))
    return {
        "franchisee": fr,
        "store": st,
        "ingredient": ing,
        "lot": lot_row,
        "menu_item": mi,
        "customer": cust,
    }


# --- Reconciliation helper ---------------------------------------------------

def setup_reconciliation_from_order(api, *, business_date, clock, order_menu, lot=None,
                                    ingredient=None, subscription=None, order_overrides=None,
                                    counted_cash_cents):
    """Build an OPEN store, place+pay+complete one order on `business_date`, then
    open and count a reconciliation for that date.

    Returns dict with: franchisee, store, customer, order, reconciliation.
    The reconciliation is left in COUNTED state, ready to post.
    """
    set_clock(api, clock)
    env = setup_order_env(api, menu=order_menu, ingredient=ingredient, lot=lot)
    fr, st, cust, mi = env["franchisee"], env["store"], env["customer"], env["menu_item"]

    if subscription is not None:
        create_subscription(api, cust["id"], **subscription)

    lines = order_overrides.pop("lines") if order_overrides and "lines" in order_overrides else \
        [order_line(mi["id"], size="SMALL")]
    order = place_order(api, st["id"], cust["id"], lines, **(order_overrides or {}))
    completed = advance_order_to_completed(api, order["id"], cust["id"], st["id"])

    rec = get_success_data(
        api.create_reconciliation(st["id"], create_reconciliation_payload(business_date),
                                  make_store_staff_headers(st["id"]))
    )
    rec = get_success_data(
        api.count_reconciliation(rec["id"], {"counted_cash_cents": counted_cash_cents},
                                 make_store_staff_headers(st["id"]))
    )
    return {
        "franchisee": fr,
        "store": st,
        "customer": cust,
        "order": completed,
        "reconciliation": rec,
    }


# --- Catering helper ---------------------------------------------------------

def setup_catering_env(api, *, clock="2026-05-30T00:00:00Z", catering_capacity=10,
                       with_vehicle=False, menu_base_price=800):
    """OPEN store (given catering_capacity), a WELLNESS_PACK menu item, a customer,
    the clock set to `clock`, and optionally one AVAILABLE delivery vehicle.

    Returns dict with: franchisee, store, menu_item, customer, vehicle (or None).
    """
    fr, st = create_open_store(api, catering_capacity=catering_capacity)
    mi = create_menu_item(api, name="Party Box", category="WELLNESS_PACK",
                          base_price_cents=menu_base_price, recipe=[], base_calories=500)
    cust = create_customer(api)
    vehicle = None
    if with_vehicle:
        vehicle = create_delivery_vehicle(api, st["id"], fr["id"], label="VAN-1",
                                          headcount_capacity=20)
    set_clock(api, clock)
    return {
        "franchisee": fr,
        "store": st,
        "menu_item": mi,
        "customer": cust,
        "vehicle": vehicle,
    }
