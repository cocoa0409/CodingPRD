"""Difficulty rule 6 — boundary-precision checks on different metrics.

Instance A: helium latex bulk tier at latex_count==25 (>=25 crosses the line).
Instance B: rental overlap capacity — aggregate exactly at boundary.
"""
from test_helpers import (
    validate_success, validate_error, api_client, ApiErrorId,
    make_store_clerk_headers,
)
from test_helpers.fixtures import (
    set_clock, create_customer, create_sku_with_stock, create_helium_tank,
    setup_draft_order, attach_helium, create_rental_contract,
    setup_tableware_sku_with_stock, create_order,
)


# =====================================================================
# Instance A — helium_latex_bulk_threshold_at_25_exact
# =====================================================================

def test_helium_fill_fee_latex_bulk_at_boundary_25():
    """PRD §3.4: "The latex line is computed as latex_count multiplied by
    175 cents per balloon, then multiplied by 0.85 if latex_count is at
    least 25 and 1.0 otherwise, and rounded half-up to whole cents."

    Design: Difficulty/boundary_precision_check/helium_latex_bulk_threshold_at_25_exact
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=10, category="DECOR")
    create_helium_tank(capacity=100)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    attach_helium(order["id"], latex_count=25, foil_count=0)
    resp = api_client.reserve_order(
        order["id"], order["version"], make_store_clerk_headers()
    )
    reserved = validate_success(resp)
    # 25 * 175 * 0.85 = 3718.75 → round_half_up → 3719
    assert reserved["helium_fee_cents"] == 3719, (
        f"latex_count=25 bulk-tier fee = round(25*175*0.85) = 3719; "
        f"got {reserved['helium_fee_cents']}"
    )


def test_helium_fill_fee_latex_just_below_bulk_at_24():
    """PRD §3.4: "The latex line is computed as latex_count multiplied by
    175 cents per balloon, then multiplied by 0.85 if latex_count is at
    least 25 and 1.0 otherwise, and rounded half-up to whole cents."

    Design: Difficulty/boundary_precision_check/helium_latex_bulk_threshold_at_25_exact
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=100, on_hand=10, category="DECOR")
    create_helium_tank(capacity=100)
    order = setup_draft_order(cust["id"], sku["id"], qty=1)
    attach_helium(order["id"], latex_count=24, foil_count=0)
    resp = api_client.reserve_order(
        order["id"], order["version"], make_store_clerk_headers()
    )
    reserved = validate_success(resp)
    # 24 * 175 * 1.0 = 4200
    assert reserved["helium_fee_cents"] == 4200, (
        f"latex_count=24 (below bulk tier) fee = 24*175 = 4200; "
        f"got {reserved['helium_fee_cents']}"
    )


# =====================================================================
# Instance B — rental_overlap_capacity_zero_remaining_at_boundary
# =====================================================================

def test_rental_overlap_capacity_exceeded_returns_error():
    """PRD §3.6: "The contract's [rental_start, rental_end) interval is
    additionally checked against every other non-terminal contract on
    the same sku_id: if the aggregate concurrent reserved quantity — the
    sum of qty across contracts whose intervals overlap this one —
    would exceed the SKU's on_hand_qty, the create is rejected with
    ERR_RENTAL_OVERLAP_CAPACITY."

    Design: Difficulty/boundary_precision_check/rental_overlap_capacity_zero_remaining_at_boundary
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    plate = setup_tableware_sku_with_stock(unit_price_cents=400, on_hand=5)
    order_a = create_order(cust["id"], channel="IN_STORE",
                           lines=[{"sku_id": plate["id"], "qty": 1}])
    create_rental_contract(
        order_a["id"], plate["id"], qty=5,
        rental_start="2026-06-16T00:00:00Z",
        rental_end="2026-06-20T00:00:00Z",
    )
    order_b = create_order(cust["id"], channel="IN_STORE",
                           lines=[{"sku_id": plate["id"], "qty": 1}])
    # qty=1 would push aggregate to 5+1=6, exceeding on_hand=5.
    resp = api_client.create_rental_contract(
        {"order_id": order_b["id"], "sku_id": plate["id"], "qty": 1,
         "rental_start": "2026-06-17T00:00:00Z",
         "rental_end": "2026-06-19T00:00:00Z"},
        make_store_clerk_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_RENTAL_OVERLAP_CAPACITY)


def test_rental_overlap_capacity_at_exact_boundary_permits():
    """PRD §3.6: "The contract's [rental_start, rental_end) interval is
    additionally checked against every other non-terminal contract on
    the same sku_id: if the aggregate concurrent reserved quantity — the
    sum of qty across contracts whose intervals overlap this one —
    would exceed the SKU's on_hand_qty, the create is rejected with
    ERR_RENTAL_OVERLAP_CAPACITY."

    Design: Difficulty/boundary_precision_check/rental_overlap_capacity_zero_remaining_at_boundary
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    plate = setup_tableware_sku_with_stock(unit_price_cents=400, on_hand=5)
    order_a = create_order(cust["id"], channel="IN_STORE",
                           lines=[{"sku_id": plate["id"], "qty": 1}])
    create_rental_contract(
        order_a["id"], plate["id"], qty=3,
        rental_start="2026-06-16T00:00:00Z",
        rental_end="2026-06-20T00:00:00Z",
    )
    order_b = create_order(cust["id"], channel="IN_STORE",
                           lines=[{"sku_id": plate["id"], "qty": 1}])
    # 3+2=5, equals on_hand=5 exactly → NOT exceeding → allowed.
    resp = api_client.create_rental_contract(
        {"order_id": order_b["id"], "sku_id": plate["id"], "qty": 2,
         "rental_start": "2026-06-17T00:00:00Z",
         "rental_end": "2026-06-19T00:00:00Z"},
        make_store_clerk_headers(),
    )
    rc = validate_success(resp, expected_status=201)
    assert rc["status"] == "RESERVED"
    assert rc["qty"] == 2
