"""Corner queue — calculations section.

Excluded stubs (variant_divergence for order_grand_total and
custom_print_fee) are owned by difficulty instance A/B in test_01.
"""
from test_helpers import (
    validate_success, api_client, make_store_clerk_headers,
    make_store_manager_headers,
)
from test_helpers.fixtures import (
    set_clock, create_customer, create_sku_with_stock,
    create_event_package, create_helium_tank,
    setup_draft_order, create_event_booking, apply_clearance,
    setup_tableware_sku_with_stock, create_rental_contract,
    create_delivery_slot, create_order, attach_helium,
    reserve_order, create_sku, restock_sku,
)
import uuid


def test_event_deposit_pinned_at_creation_matches_pct_formula():
    """PRD §3.8: "On creation, status is set to HELD and deposit_cents
    is pinned as the referenced package's base_price_cents multiplied by
    its deposit_pct and rounded half-up to whole cents."

    Design: Corner/calculations/event_deposit_pinned_at_creation_matches_pct_formula
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=5)
    pkg = create_event_package(base_price_cents=20000, deposit_pct=0.30,
                                 min_lead_days=7)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    resp = api_client.create_event_booking(
        {"order_id": order["id"], "event_package_id": pkg["id"],
         "event_date": "2026-07-30T18:00:00Z"},
        make_store_clerk_headers(),
    )
    booking = validate_success(resp, expected_status=201)
    # 20000 * 0.30 = 6000.
    assert booking["deposit_cents"] == 6000, (
        f"deposit_cents = round(20000 * 0.30) = 6000; got {booking['deposit_cents']}"
    )


def test_delivery_fee_weekend_with_setup():
    """PRD §3.4: "The delivery fee is a base plus two optional
    surcharges. Base delivery is 2500 cents. If setup_included is true,
    1500 cents is added. If the weekday of window_start in UTC is
    Saturday or Sunday, an additional 1000 cents weekend surcharge is
    added. The result is the slot's contribution to delivery_fee_cents."

    Design: Corner/calculations/delivery_fee_weekend_with_setup_included
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=5)
    # 2026-06-21 is a Sunday → weekend.
    slot = create_delivery_slot(
        "2026-06-21T10:00:00Z", "2026-06-21T12:00:00Z",
        van_id="V-SUN-" + uuid.uuid4().hex[:6], setup_included=True,
    )
    order = create_order(cust["id"], channel="DELIVERY",
                          lines=[{"sku_id": sku["id"], "qty": 1}],
                          delivery_slot_id=slot["id"])
    resp = api_client.reserve_order(
        order["id"], order["version"], make_store_clerk_headers(),
    )
    reserved = validate_success(resp)
    # 2500 base + 1500 setup + 1000 weekend = 5000.
    assert reserved["delivery_fee_cents"] == 5000, (
        f"delivery_fee_cents = 2500 base + 1500 setup + 1000 weekend "
        f"= 5000; got {reserved['delivery_fee_cents']}"
    )


def test_helium_waterfall_drains_oldest_tank_first():
    """PRD §2.10: "the server computes the required cubic feet as
    latex_count times half a cubic foot plus foil_count times one and a
    half cubic feet, then draws from HeliumTank rows with status equal
    to ACTIVE in ascending order of created_at; ties on created_at are
    broken by tank_code in ascending alphabetical order, never by id."
    PRD §2.10: "The current tank is exhausted before the next is
    touched: for each tank the server takes the smaller of the tank's
    remaining_cubic_ft and the residual required amount, appends the
    tank's id to helium_tank_ids on the HeliumOrder, and decrements
    remaining_cubic_ft accordingly."

    Design: Corner/calculations/helium_waterfall_allocates_oldest_active_tank_first
    """
    set_clock("2026-06-15T09:00:00Z")
    tank1 = create_helium_tank(capacity=10)
    # Advance clock so tank2's created_at is strictly later.
    set_clock("2026-06-15T09:30:00Z")
    tank2 = create_helium_tank(capacity=50)
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=5)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    # required = 40 * 0.5 + 0 * 1.5 = 20 cu.ft. T1 drains 10 (all), T2 drains 10.
    attach_helium(order["id"], latex_count=40, foil_count=0)
    reserve_order(order["id"], order["version"])
    r1 = api_client.get_helium_tank(tank1["id"], make_store_clerk_headers())
    r2 = api_client.get_helium_tank(tank2["id"], make_store_clerk_headers())
    t1_after = validate_success(r1)
    t2_after = validate_success(r2)
    assert t1_after["remaining_cubic_ft"] == 0, (
        f"Older tank T1 (cap 10) must drain to 0 first; "
        f"got {t1_after['remaining_cubic_ft']}"
    )
    assert t2_after["remaining_cubic_ft"] == 40, (
        f"Younger tank T2 (cap 50) must debit only residual 10 → 40 remaining; "
        f"got {t2_after['remaining_cubic_ft']}"
    )


def test_rental_deposit_ignores_clearance_discount():
    """PRD §3.6: "The rental deposit is deliberately insensitive to
    clearance discount. Let the deposit multiplier be 2.0; the per-unit
    deposit is the SKU's undiscounted unit_price_cents multiplied by
    2.0, rounded half-up to whole cents, and the contract's
    deposit_cents is that per-unit value multiplied by qty. Even when
    the underlying SKU is on clearance, the deposit uses the full
    retail unit price rather than the discounted one — this ring-fences
    the store's exposure against damage or non-return regardless of
    promotional pricing."

    Design: Corner/calculations/rental_deposit_ignores_clearance_discount
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    plate = setup_tableware_sku_with_stock(unit_price_cents=500, on_hand=20)
    apply_clearance(plate["id"], 0.5, plate["version"])
    order = create_order(cust["id"], channel="IN_STORE",
                          lines=[{"sku_id": plate["id"], "qty": 1}])
    resp = api_client.create_rental_contract(
        {"order_id": order["id"], "sku_id": plate["id"], "qty": 4,
         "rental_start": "2026-06-20T00:00:00Z",
         "rental_end": "2026-06-22T00:00:00Z"},
        make_store_clerk_headers(),
    )
    rc = validate_success(resp, expected_status=201)
    # Deposit = round(500 * 2.0) * 4 = 1000 * 4 = 4000 (undiscounted 500, not 250).
    assert rc["deposit_cents"] == 4000, (
        f"Rental deposit must use UNDISCOUNTED unit_price=500; "
        f"2 * 500 * 4 = 4000; got {rc['deposit_cents']}"
    )
