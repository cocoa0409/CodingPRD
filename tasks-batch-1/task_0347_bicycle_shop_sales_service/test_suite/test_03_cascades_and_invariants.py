"""Transitive-cascade and compensating-invariant depth tests
(PRD §2.6, §2.9, §3.5, §3.10, §3.11).

Queue A — difficulty rules transitive_cascade and compensating_invariant.
"""
from test_helpers import (
    api_client, validate_success,
    create_customer, create_sku, create_reserved_order, pay_order, get_sku,
    create_under_review_claim, seed_store_credit_via_grade_c,
    approve_warranty_payload, create_order_line_payload, reserve_payload,
    create_payment_payload,
    TEST_USERS,
)

MGR = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["sales_associate_headers"]
ADV = TEST_USERS["service_advisor_headers"]


# ════════════════════════════════════════════════════════════════════════════
# Rule 4 — transitive_cascade / deliver_commits_reservation_decrements_sku
# ════════════════════════════════════════════════════════════════════════════
def test_deliver_decrements_sku_on_hand():
    """PRD §3.5: "each `ACTIVE` reservation of the order is committed
    (`ACTIVE → COMMITTED`), decrementing both `on_hand` and `reserved` for each
    `Sku`".

    Deliver of a paid, reserved qty-2 order drops on_hand 10 -> 8 via the
    commit cascade.

    Design: Difficulty/transitive_cascade/deliver_commits_reservation_decrements_sku
    """
    cust = create_customer()
    sku = create_sku(name="Commuter Bike", category="BIKE", list_price_cents=45000, on_hand=10)
    cust2, order, line = create_reserved_order(sku["id"], qty=2, customer_id=cust["id"])
    pay_order(order["id"], order["subtotal_cents"])
    delivered = validate_success(api_client.deliver_sales_order(order["id"], SA), 200)
    assert delivered["fulfillment_status"] == "DELIVERED"
    sku_after = validate_success(api_client.get_sku(sku["id"], MGR), 200)
    assert sku_after["on_hand"] == 8


def test_deliver_clears_committed_reservation_from_reserved():
    """PRD §2.6: "committing decreases both `on_hand` and `reserved` by the
    committed quantity in the same step, so the units physically leave the
    stockroom and simultaneously leave the active reserved set".

    Deliver flips the reservation ACTIVE->COMMITTED, returning Sku.reserved
    2 -> 0.

    Design: Difficulty/transitive_cascade/deliver_commits_reservation_decrements_sku
    """
    cust = create_customer()
    sku = create_sku(name="Commuter Bike B", category="BIKE", list_price_cents=45000, on_hand=10)
    cust2, order, line = create_reserved_order(sku["id"], qty=2, customer_id=cust["id"])
    pay_order(order["id"], order["subtotal_cents"])
    validate_success(api_client.deliver_sales_order(order["id"], SA), 200)
    sku_after = validate_success(api_client.get_sku(sku["id"], MGR), 200)
    assert sku_after["reserved"] == 0


# ════════════════════════════════════════════════════════════════════════════
# Rule 4 — transitive_cascade / warranty_resolve_commits_replacement_decrements_sku
# ════════════════════════════════════════════════════════════════════════════
def _approved_replace_claim(repl_name):
    cust = create_customer()
    sku = create_sku(name="Steel Frame", category="BIKE", list_price_cents=80000,
                     on_hand=2, warranty_class="FRAME_AND_COMPONENT", is_serialized=True)
    repl = create_sku(name=repl_name, category="BIKE", list_price_cents=80000,
                      on_hand=1, warranty_class="FRAME_AND_COMPONENT", is_serialized=True)
    cust2, claim, line = create_under_review_claim(sku["id"], "FRAME", customer_id=cust["id"])
    claim = validate_success(api_client.approve_warranty_claim(
        claim["id"], approve_warranty_payload("REPLACE", resolution_sku_id=repl["id"]), ADV), 200)
    return claim, repl


def test_resolve_decrements_replacement_on_hand():
    """PRD §3.10: "The replacement is later finalized by resolving the claim,
    moving it from `APPROVED_REPLACE` to `RESOLVED`: resolving commits that
    replacement reservation (`ACTIVE → COMMITTED`), decrementing the resolution
    `Sku`'s `on_hand` and `reserved` by 1."

    Resolve drives replacement Sku.on_hand 1 -> 0 via the commit cascade.

    Design: Difficulty/transitive_cascade/warranty_resolve_commits_replacement_decrements_sku
    """
    claim, repl = _approved_replace_claim("Steel Frame Replacement")
    resolved = validate_success(api_client.resolve_warranty_claim(claim["id"], ADV), 200)
    assert resolved["status"] == "RESOLVED"
    repl_after = validate_success(api_client.get_sku(repl["id"], MGR), 200)
    assert repl_after["on_hand"] == 0


def test_resolve_clears_replacement_reserved():
    """PRD §3.10: "resolving commits that replacement reservation
    (`ACTIVE → COMMITTED`), decrementing the resolution `Sku`'s `on_hand` and
    `reserved` by 1."

    Resolve returns replacement Sku.reserved 1 -> 0.

    Design: Difficulty/transitive_cascade/warranty_resolve_commits_replacement_decrements_sku
    """
    claim, repl = _approved_replace_claim("Steel Frame Replacement B")
    validate_success(api_client.resolve_warranty_claim(claim["id"], ADV), 200)
    repl_after = validate_success(api_client.get_sku(repl["id"], MGR), 200)
    assert repl_after["reserved"] == 0


# ════════════════════════════════════════════════════════════════════════════
# Rule 9 — compensating_invariant / reserve_then_cancel_conserves_sku_units
# ════════════════════════════════════════════════════════════════════════════
def test_cancel_after_reserve_restores_on_hand():
    """PRD §3.5: "Cancellation releases each `ACTIVE` reservation of the order
    (`ACTIVE → RELEASED`), lowering each `Sku`'s `reserved`".

    Reserve (on_hand 6, reserved 2) then cancel leaves on_hand==6 — the
    pre-reserve total, with zero drift.

    Design: Difficulty/compensating_invariant/reserve_then_cancel_conserves_sku_units
    """
    cust = create_customer()
    sku = create_sku(name="Saddle", category="PART", list_price_cents=8000, on_hand=6)
    cust2, order, line = create_reserved_order(sku["id"], qty=2, customer_id=cust["id"])
    cancelled = validate_success(api_client.cancel_sales_order(order["id"], SA), 200)
    assert cancelled["fulfillment_status"] == "CANCELLED"
    sku_after = validate_success(api_client.get_sku(sku["id"], MGR), 200)
    assert sku_after["on_hand"] == 6


def test_cancel_after_reserve_returns_reserved_to_zero():
    """PRD §2.6: "When a holder is cancelled or released before delivery, its
    reservations move to `RELEASED`, which lowers `reserved` and so raises
    availability again."

    Cancel of a RESERVED order returns Sku.reserved 2 -> 0.

    Design: Difficulty/compensating_invariant/reserve_then_cancel_conserves_sku_units
    """
    cust = create_customer()
    sku = create_sku(name="Saddle B", category="PART", list_price_cents=8000, on_hand=6)
    cust2, order, line = create_reserved_order(sku["id"], qty=2, customer_id=cust["id"])
    validate_success(api_client.cancel_sales_order(order["id"], SA), 200)
    sku_after = validate_success(api_client.get_sku(sku["id"], MGR), 200)
    assert sku_after["reserved"] == 0


# ════════════════════════════════════════════════════════════════════════════
# Rule 9 — compensating_invariant / paid_order_cancel_restores_store_credit
# ════════════════════════════════════════════════════════════════════════════
def _partially_paid_credit_order():
    """Customer with 25000 store credit + a reserved, PARTIALLY_PAID order
    (subtotal 30000, paid 10000)."""
    cust = create_customer()
    seed_store_credit_via_grade_c(cust["id"], 53000)  # -> 25000 credit
    sku = create_sku(name="Helmet", category="ACCESSORY", list_price_cents=30000, on_hand=5)
    from test_helpers import create_order
    order = create_order(cust["id"])
    from test_helpers import add_order_line
    add_order_line(order["id"], sku["id"], 1)
    fresh = get_sku(sku["id"])
    validate_success(api_client.reserve_sales_order(order["id"], reserve_payload(fresh["version"]), SA), 200)
    pay_order(order["id"], 10000)
    order = validate_success(api_client.get_sales_order(order["id"], SA), 200)
    return cust, order


def test_cancel_partially_paid_order_sets_refunded():
    """PRD §3.5: "if the order's payment status was `PARTIALLY_PAID` or `PAID`,
    it sets `payment_status` to `REFUNDED`, voids all captured payments on the
    order, and restores any consumed store credit to the customer's
    `store_credit_cents` as compensation."

    Cancelling a RESERVED + PARTIALLY_PAID order sets payment_status=REFUNDED.

    Design: Difficulty/compensating_invariant/paid_order_cancel_restores_store_credit
    """
    cust, order = _partially_paid_credit_order()
    assert order["payment_status"] == "PARTIALLY_PAID"
    cancelled = validate_success(api_client.cancel_sales_order(order["id"], SA), 200)
    assert cancelled["payment_status"] == "REFUNDED"


def test_cancel_keeps_unconsumed_store_credit_intact():
    """PRD §3.5: "restores any consumed store credit to the customer's
    `store_credit_cents` as compensation."
    PRD §3.6: "Store credit is applied as a single waterfall bucket at the moment
    of delivery".

    No credit is consumed before delivery, so after cancelling the pre-delivery
    order the customer's store_credit_cents is unchanged at 25000.

    Design: Difficulty/compensating_invariant/paid_order_cancel_restores_store_credit
    """
    cust, order = _partially_paid_credit_order()
    validate_success(api_client.cancel_sales_order(order["id"], SA), 200)
    refreshed = validate_success(api_client.get_customer(cust["id"], MGR), 200)
    assert refreshed["store_credit_cents"] == 25000
