"""Sale tender/fulfillment axes, voiding, member lifecycle cascades, loyalty
tier accrual, and line unit-type safety.

Translates difficulty instances (queue A: non_linear_state_machine,
transitive_cascade) and corner instances (queue B: state_machines, calculations,
validations, errors).
"""
from test_helpers import (
    validate_success, validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    fixtures,
)

SM = TEST_USERS["store_manager_headers"]
PM = TEST_USERS["price_manager_headers"]
RC = TEST_USERS["receiving_clerk_headers"]
CSH = TEST_USERS["cashier_headers"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / sale_parallel_tender_and_fulfillment_axes
# ---------------------------------------------------------------------------
def test_finalize_advances_fulfillment_only_tender_stays_unpaid(api):
    """PRD §3.7: "It carries two independent state dimensions: a tender dimension `tender_status` that begins `UNPAID`, and a fulfillment dimension `fulfillment_status` that begins `OPEN`. These axes advance independently."
    PRD §3.7: "Finalizing advances `fulfillment_status` from `OPEN` to `FINALIZED` and is the heart of the system."

    Design: Difficulty/non_linear_state_machine/sale_parallel_tender_and_fulfillment_axes
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Soup", unit_price_cents=250, reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 10, unit_cost_cents=100)
    sale, _ = fixtures.open_sale_with_each_line(product["id"], 2)
    finalized = validate_success(api.finalize_sale(sale["id"], {}, CSH))
    assert finalized["fulfillment_status"] == "FINALIZED"
    assert finalized["tender_status"] == "UNPAID"


def test_pay_advances_tender_only_fulfillment_stays_finalized(api):
    """PRD §3.9: "Paying a sale moves `tender_status` from `UNPAID` to `PAID`; it requires the tender status to be `UNPAID`, else `ERR_SALE_NOT_UNPAID`, and gates on the fulfillment axis being `FINALIZED`, else `ERR_SALE_NOT_FINALIZED` — paying touches only the tender axis and changes no inventory."

    Design: Difficulty/non_linear_state_machine/sale_parallel_tender_and_fulfillment_axes
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Soup2", unit_price_cents=250, reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 10, unit_cost_cents=100)
    sale, _ = fixtures.open_sale_with_each_line(product["id"], 2)
    fixtures.finalize_sale(sale["id"])
    paid = validate_success(api.pay_sale(sale["id"], CSH))
    assert paid["tender_status"] == "PAID"
    assert paid["fulfillment_status"] == "FINALIZED"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / member_close_expires_clipped_coupons
# ---------------------------------------------------------------------------
def test_member_close_transitions_member_to_closed(api):
    """PRD §3.6: "Closing is permitted from either `ACTIVE` or `SUSPENDED`, else `ERR_MEMBER_NOT_CLOSEABLE`, and drives the member to `CLOSED` ..."

    Design: Difficulty/transitive_cascade/member_close_expires_clipped_coupons
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Tea", unit_price_cents=99, reorder_point_qty=0)
    coupon = fixtures.create_coupon(product["id"], code="TEA5", discount_cents=50,
                                    min_spend_cents=0)
    member, _ = fixtures.create_member_with_clip(coupon["id"], email="b@x.com")
    closed = validate_success(api.close_member(member["id"], SM))
    assert closed["status"] == "CLOSED"


def test_member_close_cascades_clipped_coupons_to_expired(api):
    """PRD §3.6: "as a cascade, every one of that member's clipped coupons that is still in `CLIPPED` is moved to `EXPIRED` and can no longer be redeemed."

    Design: Difficulty/transitive_cascade/member_close_expires_clipped_coupons
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Tea2", unit_price_cents=99, reorder_point_qty=0)
    coupon = fixtures.create_coupon(product["id"], code="TEA6", discount_cents=50,
                                    min_spend_cents=0)
    member, clip = fixtures.create_member_with_clip(coupon["id"], email="b2@x.com")
    validate_success(api.close_member(member["id"], SM))
    clip_now = get_success_data(api.get_clipped_coupon(clip["id"], CSH))
    assert clip_now["status"] == "EXPIRED"


# ---------------------------------------------------------------------------
# Corner: state_machines / void_open_sale_no_inventory_effect
# ---------------------------------------------------------------------------
def test_void_open_sale_no_inventory_effect(api):
    """PRD §3.9: "Voiding a sale is a fulfillment-axis action available only while the sale is still `OPEN` (else `ERR_SALE_NOT_OPEN`); it moves `fulfillment_status` to `VOIDED` and has no inventory or ledger effect because nothing was depleted while the sale was open."

    Design: Corner/state_machines/void_open_sale_no_inventory_effect
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Void", unit_price_cents=99, reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100)
    sale, _ = fixtures.open_sale_with_each_line(product["id"], 2)
    voided = validate_success(api.void_sale(sale["id"], CSH))
    assert voided["fulfillment_status"] == "VOIDED"
    prod = get_success_data(api.get_product(product["id"], PM))
    assert prod["on_hand_qty"] == 5


# ---------------------------------------------------------------------------
# Corner: state_machines / pay_before_finalize_returns_not_finalized
# ---------------------------------------------------------------------------
def test_pay_before_finalize_returns_not_finalized(api):
    """PRD §3.9: "it requires the tender status to be `UNPAID`, else `ERR_SALE_NOT_UNPAID`, and gates on the fulfillment axis being `FINALIZED`, else `ERR_SALE_NOT_FINALIZED` ..."

    Design: Corner/state_machines/pay_before_finalize_returns_not_finalized
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Pay", unit_price_cents=99, reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100)
    sale, _ = fixtures.open_sale_with_each_line(product["id"], 1)
    resp = api.pay_sale(sale["id"], CSH)  # still OPEN
    validate_error(resp, ApiErrorId.ERR_SALE_NOT_FINALIZED.value)


# ---------------------------------------------------------------------------
# Corner: calculations / gold_tier_doubles_points
# ---------------------------------------------------------------------------
def test_gold_tier_doubles_points(api):
    """PRD §3.9: "`GOLD` earns twice the base, with the result floored to whole
    points."
    PRD §3.9: "a member reaches `GOLD` at a lifetime spend of at least 200000 cents
    (two thousand dollars) ..."

    Design: Corner/calculations/gold_tier_doubles_points
    """
    member = fixtures.make_gold_member()
    assert member["tier"] == "GOLD"
    # Second purchase: total 1000 -> base 10 points -> GOLD x2 -> 20.
    small = fixtures.create_product(name="Small", sku="SKU-SML",
                                    unit_price_cents=250, reorder_point_qty=0)
    fixtures.receive_lot(small["id"], 10, unit_cost_cents=100)
    sale, _ = fixtures.open_sale_with_each_line(small["id"], 4, member_id=member["id"])
    finalized = fixtures.finalize_sale(sale["id"])
    assert finalized["points_earned"] == 20


# ---------------------------------------------------------------------------
# Corner: errors / duplicate_member_email_conflict
# ---------------------------------------------------------------------------
def test_duplicate_member_email_conflict(api):
    """PRD §3.6: "A loyalty member is created by a `StoreManager` or `Cashier` with an `email` (unique across members, rejected on collision with `ERR_DUPLICATE_RESOURCE`) and a `full_name`."

    Design: Corner/errors/duplicate_member_email_conflict
    """
    get_success_data(api.create_member({"email": "dup@x.com", "full_name": "First"}, CSH))
    resp = api.create_member({"email": "dup@x.com", "full_name": "Second"}, CSH)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


# ---------------------------------------------------------------------------
# Corner: validations / line_unit_mismatch_quantity_on_weighed_product
# ---------------------------------------------------------------------------
def test_line_unit_mismatch_quantity_on_weighed_product(api):
    """PRD §3.7: "The line's unit type must match the product: providing a
    `quantity` for a weighed product, or a `weight_milli` for an each-sold product,
    is rejected with `ERR_LINE_UNIT_MISMATCH`."

    Design: Corner/validations/line_unit_mismatch_quantity_on_weighed_product
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_weighed_product(name="Apples", plu="4131",
                                              unit_price_cents=199, is_perishable=True,
                                              reorder_point_qty=0)
    sale = fixtures.open_sale()
    resp = api.add_line_item(sale["id"], {"product_id": product["id"], "quantity": 3}, CSH)
    validate_error(resp, ApiErrorId.ERR_LINE_UNIT_MISMATCH.value)
