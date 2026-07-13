"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds the whole
world it needs from PRD-declared endpoints only. Setup calls use the lenient
get_success_data() validator so a broken precondition surfaces as "Setup failed"
rather than as a confusing assertion deep inside a test.

Identity threading: after a Customer or an Artist is created, every ownership-gated
call in these helpers uses make_customer_headers(customer["id"]) /
make_artist_headers(artist["id"]) — never the shared TEST_USERS constant.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    add_line_payload,
    approve_decision_payload,
    create_artist_payload,
    create_booking_payload,
    create_bundle_promotion_payload,
    create_customer_payload,
    create_gwp_promotion_payload,
    create_inventory_lot_payload,
    create_limited_variant_payload,
    create_order_payload,
    create_product_payload,
    create_return_request_payload,
    create_sample_promotion_payload,
    create_store_payload,
    create_variant_payload,
    deny_decision_payload,
    line,
    make_tester_conversion_payload,
)
from .test_users import TEST_USERS, make_artist_headers, make_customer_headers

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]


# ─── Tier 0: single-resource builders ─────────────────

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.4). Returns {current_utc, advanced_variant_ids}."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def new_store(**overrides) -> dict:
    return get_success_data(
        api_client.create_store(create_store_payload(**overrides), ADMIN)
    )


def new_product(**overrides) -> dict:
    return get_success_data(
        api_client.create_product(create_product_payload(**overrides), ADMIN)
    )


def new_variant(product_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_variant(
            product_id, create_variant_payload(**overrides), ADMIN
        )
    )


def new_limited_variant(product_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_variant(
            product_id, create_limited_variant_payload(**overrides), ADMIN
        )
    )


def new_lot(store_id: str, variant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_inventory_lot(
            create_inventory_lot_payload(store_id, variant_id, **overrides), ADMIN
        )
    )


def new_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), ADMIN)
    )


def new_artist(store_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_artist(create_artist_payload(store_id, **overrides), ADMIN)
    )


def new_gwp_promotion(gift_variant_id: str, threshold_cents: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_promotion(
            create_gwp_promotion_payload(gift_variant_id, threshold_cents, **overrides),
            ADMIN,
        )
    )


def new_sample_promotion(gift_variant_id: str, threshold_cents: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_promotion(
            create_sample_promotion_payload(
                gift_variant_id, threshold_cents, **overrides
            ),
            ADMIN,
        )
    )


def new_bundle_promotion(bundle_variant_ids, bundle_discount_pct, **overrides) -> dict:
    return get_success_data(
        api_client.create_promotion(
            create_bundle_promotion_payload(
                bundle_variant_ids, bundle_discount_pct, **overrides
            ),
            ADMIN,
        )
    )


# ─── Tier 0b: readers ─────────────────────────────────

def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, ADMIN))


def read_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_inventory_lot(lot_id, ADMIN))


def read_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, ADMIN))


def read_variant(variant_id: str) -> dict:
    return get_success_data(api_client.get_variant(variant_id, ADMIN))


def read_booking(booking_id: str) -> dict:
    return get_success_data(api_client.get_service_booking(booking_id, ADMIN))


def read_order_line(line_id: str) -> dict:
    return get_success_data(api_client.get_order_line(line_id, ADMIN))


def read_return_request(return_id: str) -> dict:
    return get_success_data(api_client.get_return_request(return_id, ADMIN))


def read_lines(order_id: str) -> list:
    resp = api_client.list_order_lines(ADMIN, params={"order_id": order_id, "limit": 100})
    return get_success_data(resp)


def read_lines_by_promotion(promotion_id: str) -> list:
    resp = api_client.list_order_lines(
        ADMIN, params={"promotion_id": promotion_id, "limit": 100}
    )
    return get_success_data(resp)


def read_ledger(customer_id: str) -> list:
    """Ledger entries for a customer, oldest first (PRD §3.4)."""
    resp = api_client.list_points_ledger(
        ADMIN, params={"customer_id": customer_id, "limit": 100}
    )
    return get_success_data(resp)


def sale_lines(order_id: str) -> list:
    return [ln for ln in read_lines(order_id) if ln["line_type"] == "SALE"]


def first_sale_line(order_id: str) -> dict:
    lines = sale_lines(order_id)
    assert lines, f"Setup failed: order {order_id} has no SALE line"
    return lines[0]


# ─── Tier 1: catalogue + stock ────────────────────────

def setup_catalog(
    *,
    units_received: int = 10,
    launch_reserved_units: int = 0,
    store_overrides: dict = None,
    product_overrides: dict = None,
    variant_overrides: dict = None,
) -> dict:
    """Store + Product + Variant + InventoryLot. The workhorse precondition."""
    store = new_store(**(store_overrides or {}))
    product = new_product(**(product_overrides or {}))
    variant = new_variant(product["id"], **(variant_overrides or {}))
    lot = new_lot(
        store["id"],
        variant["id"],
        units_received=units_received,
        launch_reserved_units=launch_reserved_units,
    )
    return {"store": store, "product": product, "variant": variant, "lot": lot}


def setup_limited_launch_catalog(
    *,
    units_received: int = 10,
    launch_reserved_units: int = 0,
    clock_to: str = None,
    store_overrides: dict = None,
    variant_overrides: dict = None,
) -> dict:
    """Store + Product + limited-launch Variant + lot, with the clock optionally
    advanced so the launch has stepped through its windows (PRD §3.6)."""
    store = new_store(**(store_overrides or {}))
    product = new_product(name="Drop Gloss", base_price_cents=2500)
    variant = new_limited_variant(product["id"], **(variant_overrides or {}))
    lot = new_lot(
        store["id"],
        variant["id"],
        units_received=units_received,
        launch_reserved_units=launch_reserved_units,
    )
    if clock_to:
        set_clock(clock_to)
        variant = read_variant(variant["id"])
    return {"store": store, "product": product, "variant": variant, "lot": lot}


# ─── Tier 2: draft orders ─────────────────────────────

def setup_draft_order(
    *,
    customer: dict = None,
    catalog: dict = None,
    quantity: int = 1,
    lines: list = None,
    as_customer: bool = False,
    **order_overrides,
) -> dict:
    """An ACTIVE store, a stocked variant, a customer and a DRAFT order.

    Returns {store, product, variant, lot, customer, order}."""
    catalog = catalog or setup_catalog()
    customer = customer or new_customer()
    lines = lines or [line(catalog["variant"]["id"], quantity)]
    headers = (
        make_customer_headers(customer["id"]) if as_customer else ASSOCIATE
    )
    order = get_success_data(
        api_client.create_order(
            create_order_payload(
                customer["id"], catalog["store"]["id"], lines, **order_overrides
            ),
            headers,
        )
    )
    return {**catalog, "customer": customer, "order": order}


def add_line(order: dict, variant_id: str, quantity: int = 1) -> dict:
    """Add a SALE line to a DRAFT order at its current version (PRD §2.8, §3.5)."""
    return get_success_data(
        api_client.add_order_line(
            order["id"],
            add_line_payload(variant_id, quantity, order["version"]),
            ASSOCIATE,
        )
    )


# ─── Tier 3: order lifecycle shortcuts ────────────────

def reserve(order_id: str) -> dict:
    return get_success_data(api_client.reserve_order(order_id, ASSOCIATE))


def authorize(order_id: str) -> dict:
    return get_success_data(api_client.pay_order(order_id, "AUTHORIZE", ASSOCIATE))


def capture(order_id: str) -> dict:
    return get_success_data(api_client.pay_order(order_id, "CAPTURE", ASSOCIATE))


def mark_ready(order_id: str) -> dict:
    return get_success_data(api_client.fulfill_order(order_id, "MARK_READY", ASSOCIATE))


def hand_over(order_id: str) -> dict:
    return get_success_data(api_client.fulfill_order(order_id, "HAND_OVER", ASSOCIATE))


def ship(order_id: str) -> dict:
    return get_success_data(api_client.fulfill_order(order_id, "SHIP", ASSOCIATE))


def setup_reserved_order(**kwargs) -> dict:
    """DRAFT order walked to RESERVED. Returns the setup_draft_order dict with the
    reserved order body under `order`."""
    ctx = setup_draft_order(**kwargs)
    ctx["order"] = reserve(ctx["order"]["id"])
    return ctx


def setup_captured_order(**kwargs) -> dict:
    """RESERVED order walked through AUTHORIZE then CAPTURE."""
    ctx = setup_reserved_order(**kwargs)
    authorize(ctx["order"]["id"])
    ctx["order"] = capture(ctx["order"]["id"])
    return ctx


def setup_shipped_order(**kwargs) -> dict:
    """A SHIP_FROM_STORE order walked all the way to SHIPPED + CAPTURED.

    Adds `line` (the order's first SALE line) to the returned context — the anchor
    every return-request test needs."""
    ctx = setup_captured_order(**kwargs)
    ctx["order"] = ship(ctx["order"]["id"])
    ctx["line"] = first_sale_line(ctx["order"]["id"])
    ctx["lot"] = read_lot(ctx["lot"]["id"])
    return ctx


def setup_picked_up_bopis_order(*, pickup_slot_start: str, **kwargs) -> dict:
    """A BOPIS order walked to PICKED_UP: reserve, authorize, capture, mark ready, hand over."""
    ctx = setup_captured_order(
        channel="BOPIS", pickup_slot_start=pickup_slot_start, **kwargs
    )
    mark_ready(ctx["order"]["id"])
    ctx["order"] = hand_over(ctx["order"]["id"])
    ctx["line"] = first_sale_line(ctx["order"]["id"])
    return ctx


# ─── Tier 4: returns ──────────────────────────────────

def request_return(line_id: str, customer_id: str, quantity: int = 1, **overrides) -> dict:
    return get_success_data(
        api_client.create_return_request(
            create_return_request_payload(line_id, quantity, **overrides),
            make_customer_headers(customer_id),
        )
    )


def approve_return(return_id: str) -> dict:
    return get_success_data(
        api_client.decide_return_request(
            return_id, approve_decision_payload(), ASSOCIATE
        )
    )


def deny_return(return_id: str, deny_reason: str = "OUT_OF_POLICY") -> dict:
    return get_success_data(
        api_client.decide_return_request(
            return_id, deny_decision_payload(deny_reason), ASSOCIATE
        )
    )


def setup_requested_return(*, quantity: int = 1, return_quantity: int = 1, **kwargs) -> dict:
    """A SHIPPED, CAPTURED order with one REQUESTED ReturnRequest against its sale line."""
    ctx = setup_shipped_order(quantity=quantity, **kwargs)
    ctx["return_request"] = request_return(
        ctx["line"]["id"], ctx["customer"]["id"], return_quantity
    )
    return ctx


def setup_suspended_customer(*, strikes: int = 3) -> dict:
    """Drive a customer to `strikes` HYGIENE_VIOLATION denials so return_privilege
    flips to SUSPENDED (PRD §3.9)."""
    ctx = setup_shipped_order(quantity=4)
    for _ in range(strikes):
        rr = request_return(ctx["line"]["id"], ctx["customer"]["id"], 1, reason="DAMAGED")
        deny_return(rr["id"], "HYGIENE_VIOLATION")
    ctx["customer"] = read_customer(ctx["customer"]["id"])
    return ctx


# ─── Tier 5: inventory lots / testers ─────────────────

def convert_testers(lot_id: str, units: int, expected_lot_version: int) -> dict:
    return get_success_data(
        api_client.convert_testers(
            lot_id, make_tester_conversion_payload(units, expected_lot_version), ASSOCIATE
        )
    )


# ─── Tier 6: service bookings ─────────────────────────

def setup_artist_and_customer(*, skills=None, store: dict = None) -> dict:
    store = store or new_store()
    artist = new_artist(store["id"], skills=skills or ["BROW", "MAKEOVER"])
    customer = new_customer()
    return {"store": store, "artist": artist, "customer": customer}


def book_service(
    ctx: dict, start_at: str, *, customer: dict = None, **overrides
) -> dict:
    """Create a CONFIRMED booking for ctx's artist. `ctx` needs store + artist."""
    customer = customer or ctx["customer"]
    return get_success_data(
        api_client.create_service_booking(
            create_booking_payload(
                customer["id"], ctx["store"]["id"], ctx["artist"]["id"], start_at,
                **overrides,
            ),
            make_customer_headers(customer["id"]),
        )
    )


def setup_confirmed_booking(
    *, start_at: str = "2026-06-05T10:00:00Z", service_type: str = "BROW", skills=None
) -> dict:
    """Store + artist + customer + one CONFIRMED booking."""
    ctx = setup_artist_and_customer(skills=skills)
    ctx["booking"] = book_service(ctx, start_at, service_type=service_type)
    return ctx


def reschedule(booking_id: str, customer_id: str, proposed_start_at: str) -> dict:
    return get_success_data(
        api_client.reschedule_booking(
            booking_id, proposed_start_at, make_customer_headers(customer_id)
        )
    )


def confirm(booking_id: str, artist_id: str) -> dict:
    return get_success_data(
        api_client.confirm_booking(booking_id, make_artist_headers(artist_id))
    )


def complete(booking_id: str, artist_id: str, outcome: str = "COMPLETED") -> dict:
    return get_success_data(
        api_client.complete_booking(
            booking_id, outcome, make_artist_headers(artist_id)
        )
    )


def setup_booking_at_max_reschedules() -> dict:
    """Two full reschedule -> confirm loops, leaving reschedule_count at 2 (PRD §3.8)."""
    ctx = setup_confirmed_booking()
    bk_id, artist_id, cust_id = (
        ctx["booking"]["id"],
        ctx["artist"]["id"],
        ctx["customer"]["id"],
    )
    reschedule(bk_id, cust_id, "2026-06-05T13:00:00Z")
    confirm(bk_id, artist_id)
    reschedule(bk_id, cust_id, "2026-06-05T16:00:00Z")
    ctx["booking"] = confirm(bk_id, artist_id)
    return ctx


def setup_booking_linked_to_order(
    *, start_at: str = "2026-06-05T10:00:00Z", capture_payment: bool = True
) -> dict:
    """A customer with an order at a store, plus a CONFIRMED MAKEOVER booking linked
    to that order. When capture_payment is False the order stops at AUTHORIZED."""
    store = new_store()
    artist = new_artist(store["id"], skills=["BROW", "MAKEOVER"])
    product = new_product()
    variant = new_variant(product["id"])
    lot = new_lot(store["id"], variant["id"], units_received=10)
    catalog = {"store": store, "product": product, "variant": variant, "lot": lot}
    customer = new_customer()
    ctx = setup_draft_order(customer=customer, catalog=catalog, quantity=1)
    reserve(ctx["order"]["id"])
    authorize(ctx["order"]["id"])
    if capture_payment:
        capture(ctx["order"]["id"])
    ctx["order"] = read_order(ctx["order"]["id"])
    ctx["artist"] = artist
    ctx["booking"] = book_service(
        ctx,
        start_at,
        service_type="MAKEOVER",
        linked_order_id=ctx["order"]["id"],
    )
    return ctx


# ─── Tier 7: BOPIS slot occupancy ─────────────────────

def setup_full_bopis_slot(
    *, pickup_slot_start: str = "2026-06-05T14:00:00Z", capacity: int = 2
) -> dict:
    """Fill a pickup slot to exactly `capacity` RESERVED BOPIS orders, and leave one
    further DRAFT order aimed at the same slot (PRD §3.6)."""
    catalog = setup_catalog(
        units_received=10, store_overrides={"bopis_slot_capacity": capacity}
    )
    customer = new_customer()
    reserved = []
    for _ in range(capacity):
        ctx = setup_draft_order(
            customer=customer,
            catalog=catalog,
            quantity=1,
            channel="BOPIS",
            pickup_slot_start=pickup_slot_start,
        )
        reserved.append(reserve(ctx["order"]["id"]))
    pending = setup_draft_order(
        customer=customer,
        catalog=catalog,
        quantity=1,
        channel="BOPIS",
        pickup_slot_start=pickup_slot_start,
    )["order"]
    return {
        **catalog,
        "customer": customer,
        "reserved_orders": reserved,
        "pending_order": pending,
    }
