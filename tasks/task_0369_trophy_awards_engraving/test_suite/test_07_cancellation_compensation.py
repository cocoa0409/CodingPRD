"""Cancellation: compensating release / un-redeem / refund invariants, terminal lockdown (A + B)."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    make_customer_headers,
    make_staff_headers,
    make_manager_headers,
    fixtures,
    factories,
)

STAFF = make_staff_headers()
MANAGER = make_manager_headers()


# ─── compensating_invariant: on_hand_qty conserved across reserve/release ───
def test_cancel_release_conserves_on_hand_qty(api):
    """PRD §3.9: "All of the order's `RESERVED` component allocations advance `RESERVED →
    RELEASED`, and each affected component's `allocated_qty`, `available_qty`, and
    `low_stock` are recomputed (the physical `on_hand_qty` is unchanged, since released
    materials were never consumed)."

    Design: Difficulty/compensating_invariant/cancel_release_conserves_on_hand_qty
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    component = fixtures.create_component(on_hand_qty=7, reorder_point=0)
    product = fixtures.create_product(
        component["id"], sku="ASA-17", base_price_cents=1000,
        engraving_price_per_char_cents=0, standard_lead_days=3,
    )
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    order = fixtures.create_order(customer)
    line = fixtures.add_line(order, customer, product["id"], quantity=2)
    fixtures.add_approved_proof(line, customer, content_ref="X")
    priced = fixtures.price(order, customer)
    validate_success(
        api.confirm_order(order["id"], {"expected_order_version": priced["version"]}, cust)
    )
    cancelled = validate_success(api.cancel_order(order["id"], MANAGER))
    assert cancelled["production_status"] == "CANCELLED"
    allocs, _meta = validate_paginated(api.list_line_component_allocations(line["id"], STAFF))
    assert allocs[0]["alloc_status"] == "RELEASED"
    comp = validate_success(api.get_component(component["id"], STAFF))
    assert comp["on_hand_qty"] == 7
    assert comp["allocated_qty"] == 0
    assert comp["available_qty"] == 7


def test_cancel_release_restores_available_qty_to_pre_confirm(api):
    """PRD §3.9: "All of the order's `RESERVED` component allocations advance `RESERVED →
    RELEASED`, and each affected component's `allocated_qty`, `available_qty`, and
    `low_stock` are recomputed (the physical `on_hand_qty` is unchanged, since released
    materials were never consumed)."

    Design: Difficulty/compensating_invariant/cancel_release_conserves_on_hand_qty
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    component = fixtures.create_component(on_hand_qty=7, reorder_point=0)
    product = fixtures.create_product(
        component["id"], sku="ASA-17B", base_price_cents=1000,
        engraving_price_per_char_cents=0, standard_lead_days=3,
    )
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    order = fixtures.create_order(customer)
    line = fixtures.add_line(order, customer, product["id"], quantity=2)
    fixtures.add_approved_proof(line, customer, content_ref="X")
    priced = fixtures.price(order, customer)
    validate_success(
        api.confirm_order(order["id"], {"expected_order_version": priced["version"]}, cust)
    )
    after_confirm = validate_success(api.get_component(component["id"], STAFF))
    assert after_confirm["available_qty"] == 5  # 7 on_hand - 2 reserved
    validate_success(api.cancel_order(order["id"], MANAGER))
    after_cancel = validate_success(api.get_component(component["id"], STAFF))
    # available_qty restored to the pre-confirm value of 7 (allocated back to 0).
    assert after_cancel["available_qty"] == 7
    assert after_cancel["allocated_qty"] == 0


def test_cancel_unredeem_conserves_promo_uses_count(api):
    """PRD §3.9: "If the order had reached `CONFIRMED` or beyond and thereby redeemed its
    promo, the promo's `uses_count` is decremented by 1 to compensate."

    Design: Difficulty/compensating_invariant/cancel_unredeem_conserves_promo_uses_count
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    promo = fixtures.create_promo(code="FLAT10", kind="FLAT", flat_off_cents=1000,
                                  min_subtotal_cents=5000, max_uses=1)
    component = fixtures.create_component(on_hand_qty=10)
    product = fixtures.create_product(
        component["id"], sku="ASA-18", base_price_cents=3000,
        engraving_price_per_char_cents=0, standard_lead_days=5,
    )
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    order = fixtures.create_order(customer, service_level="EXPEDITED",
                                  due_date="2026-06-18T00:00:00Z", promo_code_id=promo["id"])
    line = fixtures.add_line(order, customer, product["id"], quantity=2)
    fixtures.add_approved_proof(line, customer, content_ref="X")
    priced = fixtures.price(order, customer)
    confirmed = validate_success(
        api.confirm_order(order["id"], {"expected_order_version": priced["version"]}, cust)
    )
    assert confirmed["invoice_total_cents"] == 6500
    cancelled = validate_success(api.cancel_order(order["id"], MANAGER))
    assert cancelled["production_status"] == "CANCELLED"
    promo_reread = validate_success(api.get_promo_code(promo["id"], cust))
    assert promo_reread["uses_count"] == 0


def test_cancel_refunds_captured_payments(api):
    """PRD §3.9: "If any money had been captured — that is, the order's `amount_paid_cents`
    is greater than 0 — every `CAPTURED` payment is moved to `REFUNDED`, the order's
    `payment_status` is set to `REFUNDED`, and its `amount_paid_cents` is reset to 0."

    Design: Difficulty/compensating_invariant/cancel_unredeem_conserves_promo_uses_count
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    promo = fixtures.create_promo(code="FLAT10B", kind="FLAT", flat_off_cents=1000,
                                  min_subtotal_cents=5000, max_uses=1)
    component = fixtures.create_component(on_hand_qty=10)
    product = fixtures.create_product(
        component["id"], sku="ASA-18B", base_price_cents=3000,
        engraving_price_per_char_cents=0, standard_lead_days=5,
    )
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    order = fixtures.create_order(customer, service_level="EXPEDITED",
                                  due_date="2026-06-18T00:00:00Z", promo_code_id=promo["id"])
    line = fixtures.add_line(order, customer, product["id"], quantity=2)
    fixtures.add_approved_proof(line, customer, content_ref="X")
    priced = fixtures.price(order, customer)
    confirmed = validate_success(
        api.confirm_order(order["id"], {"expected_order_version": priced["version"]}, cust)
    )
    fixtures.pay(order, customer, confirmed["deposit_due_cents"], "DEPOSIT")
    validate_success(api.cancel_order(order["id"], MANAGER))
    reread = validate_success(api.get_order(order["id"], cust))
    assert reread["payment_status"] == "REFUNDED"
    assert reread["amount_paid_cents"] == 0


# ─── Corner: terminal state lockdown — cannot cancel a FULFILLED order ───
def test_cancel_fulfilled_order_returns_invalid_state(api):
    """PRD §3.9: "Cancelling moves a non-terminal order — one whose `production_status` is
    `DRAFT`, `PRICED`, `CONFIRMED`, or `IN_PRODUCTION` — to `CANCELLED`; the two terminal
    states, `FULFILLED` and `CANCELLED`, reject cancellation with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_fulfilled_order_returns_invalid_state
    """
    ctx = fixtures.setup_fulfilled_order(
        product_overrides={"base_price_cents": 10000, "standard_lead_days": 3}, on_hand_qty=10
    )
    order, cust_obj = ctx["order"], ctx["customer"]
    cust = make_customer_headers(cust_obj["id"])
    resp = api.cancel_order(order["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    reread = validate_success(api.get_order(order["id"], cust))
    assert reread["production_status"] == "FULFILLED"
    assert reread["due_date_met"] is True
