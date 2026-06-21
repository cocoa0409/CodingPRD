"""Dual-variant and combinatorial calculation depth tests (PRD §3.3, §3.7, §3.9, §3.6).

Queue A — difficulty rules dual_variant_calc and combinatorial_formula.
"""
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_customer, create_sku, create_tier, create_ticket, add_labor_line,
    create_approved_repair_claim, open_layaway_with_deposit,
    create_assembling_build, seed_store_credit_via_grade_c,
    create_reserved_order, pay_order, get_sku,
    create_service_ticket_payload, create_order_line_payload, reserve_payload,
    create_payment_payload,
    TEST_USERS,
)

MGR = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["sales_associate_headers"]
ADV = TEST_USERS["service_advisor_headers"]


# ════════════════════════════════════════════════════════════════════════════
# Rule 1 — dual_variant_calc / ticket_quote_paid_vs_warranty_billing
# ════════════════════════════════════════════════════════════════════════════
def test_paid_ticket_bills_full_labor_subtotal():
    """PRD §3.3: "The amount the customer owes depends on whether the ticket is
    warranty work: when `warranty_claim_id` is set, `customer_owes_cents` is 0
    even though `labor_subtotal_cents` is still computed in full; otherwise
    `customer_owes_cents` equals `labor_subtotal_cents`."

    Paid-work variant: a BASIC tier (base 8000) plus one 3000 labor line gives
    labor_subtotal_cents=11000 and customer_owes_cents=11000.

    Design: Difficulty/dual_variant_calc/ticket_quote_paid_vs_warranty_billing
    """
    cust = create_customer()
    tier = create_tier(code="BASIC", base_labor_cents=8000, turnaround_hours=5)
    ticket = create_ticket(cust["id"], tier["id"])
    add_labor_line(ticket["id"], labor_cents=3000)
    quoted = validate_success(api_client.quote_service_ticket(ticket["id"], ADV), 200)
    assert quoted["labor_subtotal_cents"] == 11000
    assert quoted["customer_owes_cents"] == 11000


def test_warranty_ticket_owes_zero_for_same_labor_subtotal():
    """PRD §3.3: "when `warranty_claim_id` is set, `customer_owes_cents` is 0
    even though `labor_subtotal_cents` is still computed in full".

    Warranty-work variant on the SAME labor inputs (BASIC base 8000 + 3000 line)
    yields labor_subtotal_cents=11000 but customer_owes_cents=0.

    Design: Difficulty/dual_variant_calc/ticket_quote_paid_vs_warranty_billing
    """
    cust = create_customer()
    tier = create_tier(code="BASIC", base_labor_cents=8000, turnaround_hours=5)
    sku = create_sku(name="Hydraulic Brake", category="PART", list_price_cents=9000,
                     on_hand=5, warranty_class="COMPONENT")
    # create_approved_repair_claim delivers a covered purchase for this customer.
    cust2, claim, line = create_approved_repair_claim(sku["id"], "COMPONENT",
                                                      customer_id=cust["id"])
    warr_ticket = create_ticket(cust["id"], tier["id"], warranty_claim_id=claim["id"])
    add_labor_line(warr_ticket["id"], labor_cents=3000)
    quoted = validate_success(api_client.quote_service_ticket(warr_ticket["id"], ADV), 200)
    assert quoted["labor_subtotal_cents"] == 11000
    assert quoted["customer_owes_cents"] == 0


# ════════════════════════════════════════════════════════════════════════════
# Rule 1 — dual_variant_calc / layaway_settlement_forfeit_vs_cancel
# ════════════════════════════════════════════════════════════════════════════
def test_layaway_forfeit_withholds_percentage_fee():
    """PRD §3.7: "The fee in the forfeit case is the larger of a flat floor of
    2000 cents and fifteen percent of `price_cents` ... but never more than the
    accrued `deposit_cents` ... The `refund_cents` is then `deposit_cents` minus
    `forfeit_fee_cents`".

    Price 40000, deposit 15000: 15% of 40000 = 6000 (> floor 2000, < deposit),
    so forfeit_fee_cents=6000 and refund_cents=9000.

    Design: Difficulty/dual_variant_calc/layaway_settlement_forfeit_vs_cancel
    """
    cust = create_customer()
    sku = create_sku(name="City Bike", category="BIKE", list_price_cents=40000, on_hand=4)
    plan = open_layaway_with_deposit(cust["id"], sku["id"], 15000)
    forfeited = validate_success(api_client.forfeit_layaway_plan(plan["id"], MGR), 200)
    assert forfeited["forfeit_fee_cents"] == 6000
    assert forfeited["refund_cents"] == 9000


def test_layaway_cancel_refunds_full_deposit():
    """PRD §3.7: "When a `SalesAssociate` cancels an `ACTIVE` plan to
    `CANCELLED`, the reservation is likewise released ... but the cancel variant
    withholds nothing: `forfeit_fee_cents` is 0 and `refund_cents` is the full
    accrued `deposit_cents`".

    Identical deposit 15000: forfeit_fee_cents=0 and refund_cents=15000.

    Design: Difficulty/dual_variant_calc/layaway_settlement_forfeit_vs_cancel
    """
    cust = create_customer()
    sku = create_sku(name="City Bike 2", category="BIKE", list_price_cents=40000, on_hand=4)
    plan = open_layaway_with_deposit(cust["id"], sku["id"], 15000)
    cancelled = validate_success(api_client.cancel_layaway_plan(plan["id"], SA), 200)
    assert cancelled["forfeit_fee_cents"] == 0
    assert cancelled["refund_cents"] == 15000


# ════════════════════════════════════════════════════════════════════════════
# Rule 2 — combinatorial_formula / build_fee_marginal_tiered_mode_a
# ════════════════════════════════════════════════════════════════════════════
def test_build_fee_marginal_tiers_for_eight_parts():
    """PRD §3.9: "So the fee is the base, plus the smaller of the count and five
    multiplied by 1200 cents, plus — when the count exceeds five — the quantity
    (the smaller of the count and ten, minus five) multiplied by 900 cents, plus
    — when the count exceeds ten — the count minus ten multiplied by 600 cents."

    required_part_count=8: 5000 + 5*1200 + 3*900 = 13700 (two marginal bands).

    Design: Difficulty/combinatorial_formula/build_fee_marginal_tiered_mode_a
    """
    cust = create_customer()
    frame = create_sku(name="Frame XL", category="BIKE", list_price_cents=50000, on_hand=3)
    part = create_sku(name="Generic Part", category="PART", list_price_cents=1000, on_hand=50)
    build = create_assembling_build(cust["id"], frame["id"], part["id"], 8)
    assert build["status"] == "ASSEMBLING"
    assert build["build_fee_cents"] == 13700


def test_build_fee_status_advances_to_assembling_on_start():
    """PRD §3.9: "From `PARTS_RESERVED` the advisor starts assembly, moving the
    job to `ASSEMBLING`; starting computes the assembly fee (below) and
    increments the `version`."

    The same 8-part build reaches ASSEMBLING with a non-zero computed fee.

    Design: Difficulty/combinatorial_formula/build_fee_marginal_tiered_mode_a
    """
    cust = create_customer()
    frame = create_sku(name="Frame XL2", category="BIKE", list_price_cents=50000, on_hand=3)
    part = create_sku(name="Generic Part 2", category="PART", list_price_cents=1000, on_hand=50)
    build = create_assembling_build(cust["id"], frame["id"], part["id"], 8)
    assert build["status"] == "ASSEMBLING"
    assert build["build_fee_cents"] == 13700


# ════════════════════════════════════════════════════════════════════════════
# Rule 2 — combinatorial_formula / store_credit_then_total_due_eval_order_mode_c
# ════════════════════════════════════════════════════════════════════════════
def _seeded_credit_order(credit_appraised, sku_price, qty):
    """Helper: customer with grade-C store credit + a reserved, fully-paid order."""
    cust = create_customer()
    seed_store_credit_via_grade_c(cust["id"], credit_appraised)
    sku = create_sku(name="Trail Bike", category="BIKE", list_price_cents=sku_price, on_hand=10)
    order = get_success_data(api_client.create_sales_order({"customer_id": cust["id"]}, SA))
    get_success_data(api_client.create_order_line(
        create_order_line_payload(order["id"], sku["id"], qty), SA))
    fresh = get_sku(sku["id"])
    get_success_data(api_client.reserve_sales_order(order["id"], reserve_payload(fresh["version"]), SA))
    order = get_success_data(api_client.get_sales_order(order["id"], SA))
    pay_order(order["id"], order["subtotal_cents"])
    return cust, sku, order


def test_delivery_applies_store_credit_before_computing_total_due():
    """PRD §3.6: "Store credit is applied as a single waterfall bucket at the
    moment of delivery, before the fully-paid precondition is re-evaluated. The
    credit applied is the smaller of the customer's `store_credit_cents` and the
    order's `subtotal_cents`, and the order's `total_due_cents` becomes
    `subtotal_cents` minus that applied amount."

    Subtotal 60000, credit 25000: applied=25000 first, then total_due=35000.

    Design: Difficulty/combinatorial_formula/store_credit_then_total_due_eval_order_mode_c
    """
    cust, sku, order = _seeded_credit_order(53000, 30000, 2)
    assert order["subtotal_cents"] == 60000
    delivered = validate_success(api_client.deliver_sales_order(order["id"], SA), 200)
    assert delivered["store_credit_applied_cents"] == 25000
    assert delivered["total_due_cents"] == 35000


def test_delivery_deducts_applied_credit_from_customer_balance():
    """PRD §3.6: "The same applied amount is deducted from the customer's
    `store_credit_cents`."

    Customer holding 25000 has it fully consumed (applied=25000) at delivery,
    leaving store_credit_cents=0.

    Design: Difficulty/combinatorial_formula/store_credit_then_total_due_eval_order_mode_c
    """
    cust, sku, order = _seeded_credit_order(53000, 30000, 2)
    validate_success(api_client.deliver_sales_order(order["id"], SA), 200)
    refreshed = validate_success(api_client.get_customer(cust["id"], MGR), 200)
    assert refreshed["store_credit_cents"] == 0
