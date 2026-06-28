"""Retail sale void / stock conservation, package-refund preconditions, stock and prepay
fiscal validations, and the existence-over-fiscal validation-priority pair.

Queue A (Difficulty): compensating_invariant/ci_stock_conservation_sell_then_void;
                      priority_pair_validation_conflict/ppv_existence_vs_fiscal_on_retail_sale.
Queue B (Corner): section `state_machines` (void-already-voided, package refund after use);
                  section `validations` (insufficient stock / prepay).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_product, create_member, create_stylist,
    setup_sold_retail_sale, setup_base_scenario, drive_to_completed,
    setup_completed_prepay, TEST_USERS, NON_EXISTENT_UUID,
)

FD = TEST_USERS["front_desk_headers"]
FM = TEST_USERS["finance_manager_headers"]


# ─── Queue A: stock conservation sell-then-void ───────────────────────────────

def test_stock_conservation_sell_then_void(api):
    """PRD §3.12: "Recording the sale decrements the product's `stock_qty` by the quantity
    ..."
    PRD §3.12: "Voiding restores the product's `stock_qty` by the sale's `quantity` and
    reverses the `retail_commission_cents`, recomputing the attributed stylist's
    `earned_commission_cents` downward."

    Stock 10 -> sell 3 -> 7 -> void -> 10 exactly.

    Design: Difficulty/compensating_invariant/ci_stock_conservation_sell_then_void
    """
    prod, member, sale = setup_sold_retail_sale(initial_stock=10, quantity=3, unit_price=2500)
    mid = validate_success(api.get_product(prod["id"], FD), 200)
    assert mid["stock_qty"] == 7
    voided = validate_success(api.void_retail_sale(sale["id"], FD), 200)
    assert voided["status"] == "VOIDED"
    after = validate_success(api.get_product(prod["id"], FD), 200)
    assert after["stock_qty"] == 10


# ─── Queue A: existence (p3) beats fiscal (p13) on retail sale ────────────────

def test_retail_sale_nonexistent_product_returns_not_found_over_stock(api):
    """PRD §2.9: "Existence of every referenced resource comes third, yielding the
    appropriate 404 from §2.7. Request well-formedness comes fourth ... Only after all of
    these pass does the system evaluate the domain-specific temporal, capacity, and fiscal
    rules described in §3 ... and stock ..."
    PRD §2.7: "attachment and retail flows extend the same idea to `add_on_id` and
    `product_id`."

    A sale naming a non-existent product AND an over-stock quantity fails existence
    (ERR_PRODUCT_NOT_FOUND, 404), not fiscal (ERR_INSUFFICIENT_STOCK).

    Design: Difficulty/priority_pair_validation_conflict/ppv_existence_vs_fiscal_on_retail_sale
    """
    member = create_member(full_name="Buyer")
    res = api.create_retail_sale(
        {"product_id": NON_EXISTENT_UUID, "member_id": member["id"], "quantity": 9999}, FD)
    validate_error(res, "ERR_PRODUCT_NOT_FOUND", expected_status=404)


def test_stock_conservation_at_different_magnitude(api):
    """PRD §3.12: "Recording the sale decrements the product's `stock_qty` by the quantity
    ..."
    PRD §3.12: "Voiding restores the product's `stock_qty` by the sale's `quantity` ..."

    Stock 8 -> sell 5 -> 3 -> void -> 8 exactly (conservation holds at a different
    magnitude than the 10/3 case).

    Design: Difficulty/compensating_invariant/ci_stock_conservation_sell_then_void
    """
    prod, member, sale = setup_sold_retail_sale(initial_stock=8, quantity=5, unit_price=2000)
    mid = validate_success(api.get_product(prod["id"], FD), 200)
    assert mid["stock_qty"] == 3
    validate_success(api.void_retail_sale(sale["id"], FD), 200)
    after = validate_success(api.get_product(prod["id"], FD), 200)
    assert after["stock_qty"] == 8


def test_retail_sale_nonexistent_member_returns_not_found_over_stock(api):
    """PRD §2.9: "Existence of every referenced resource comes third, yielding the
    appropriate 404 from §2.7 ... Only after all of these pass does the system evaluate the
    domain-specific temporal, capacity, and fiscal rules described in §3 ... and stock ..."
    PRD §2.7: "The first reference that does not resolve aborts the request with the
    corresponding not-found error — `ERR_MEMBER_NOT_FOUND` ... each carrying HTTP 404."

    A sale against an EXISTING product but a NON-EXISTENT buyer with an over-stock quantity
    fails existence (ERR_MEMBER_NOT_FOUND, 404), never reaching the fiscal stock check.

    Design: Difficulty/priority_pair_validation_conflict/ppv_existence_vs_fiscal_on_retail_sale
    """
    prod = create_product(sku="EX-01", name="Existing", unit_price_cents=2000, initial_stock=5)
    res = api.create_retail_sale(
        {"product_id": prod["id"], "member_id": NON_EXISTENT_UUID, "quantity": 9999}, FD)
    validate_error(res, "ERR_MEMBER_NOT_FOUND", expected_status=404)


# ─── Queue B: void already-voided sale; stock not double-restored ─────────────

def test_void_already_voided_sale_rejected(api):
    """PRD §3.12: "A `FrontDesk` operator voids a sale, advancing `SOLD → VOIDED`; this
    requires the sale to be `SOLD` (otherwise `ERR_SALE_NOT_VOIDABLE`, 409)."

    Design: Corner/state_machines/sm_void_already_voided_sale_rejected
    """
    prod, member, sale = setup_sold_retail_sale(initial_stock=5, quantity=2, unit_price=2000)
    validate_success(api.void_retail_sale(sale["id"], FD), 200)
    res = api.void_retail_sale(sale["id"], FD)
    validate_error(res, "ERR_SALE_NOT_VOIDABLE", expected_status=409)
    after = validate_success(api.get_product(prod["id"], FD), 200)
    assert after["stock_qty"] == 5


# ─── Queue B: package refund after credits used ───────────────────────────────

def test_package_refund_after_credits_used_rejected(api):
    """PRD §3.13: "it requires the member's `blowout_credit_balance` to be at least the
    package's `credits_purchased`, meaning the purchased credits are still unconsumed
    (otherwise `ERR_CREDITS_ALREADY_USED`, 409) ..."

    A non-member buys a 2-credit package, a booking consumes 1 credit (balance 1 < 2);
    refunding the package is rejected.

    Design: Corner/state_machines/sm_package_refund_after_credits_used_rejected
    """
    scenario = setup_base_scenario(
        service_overrides={"base_price_cents": 6000, "blowout_credit_cost": 1})
    member_id = scenario["member"]["id"]
    mem = validate_success(api.get_member(member_id, FD), 200)
    pkg = validate_success(api.create_package_purchase(
        {"member_id": member_id, "credits_purchased": 2, "price_cents": 10000,
         "expected_member_version": mem["version"]}, FD), 201)
    # A booking consumes one credit.
    from test_helpers import book_standalone_appointment
    book_standalone_appointment(scenario)
    mem2 = validate_success(api.get_member(member_id, FD), 200)
    assert mem2["blowout_credit_balance"] == 1
    res = api.refund_package_purchase(
        pkg["id"], {"expected_member_version": mem2["version"]}, FM)
    validate_error(res, "ERR_CREDITS_ALREADY_USED", expected_status=409)


# ─── Queue B: insufficient stock / prepay fiscal validations ──────────────────

def test_insufficient_stock_rejected(api):
    """PRD §3.12: "The sale's `quantity` may not exceed the product's `stock_qty` at sale
    time, or it is rejected with `ERR_INSUFFICIENT_STOCK` (409)."

    Design: Corner/validations/val_insufficient_stock_rejected
    """
    prod = create_product(sku="ST-01", name="Spray", unit_price_cents=3000, initial_stock=10)
    member = create_member(full_name="Buyer")
    res = api.create_retail_sale(
        {"product_id": prod["id"], "member_id": member["id"], "quantity": 11}, FD)
    validate_error(res, "ERR_INSUFFICIENT_STOCK", expected_status=409)


def test_insufficient_prepay_on_settle_rejected(api):
    """PRD §3.10: "When `payment_method` is `PREPAY`, the member's `prepay_balance_cents`
    must be at least the appointment's `service_charge_cents`, or the settlement is
    rejected with `ERR_INSUFFICIENT_PREPAY` (HTTP 402)."

    Member prepay 5000, PREPAY appointment charge 6000 -> settle rejected.

    Design: Corner/validations/val_insufficient_prepay_on_settle_rejected
    """
    scenario, appt = setup_completed_prepay(prepay_amount=5000, service_price=6000)
    res = api.settle_appointment(appt["id"], {"tip_cents": 0}, FM)
    validate_error(res, "ERR_INSUFFICIENT_PREPAY", expected_status=402)
