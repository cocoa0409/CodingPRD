"""Subscription-charge and special-order-invoice pricing, plus wallet settlement."""
from test_helpers import (
    validate_success, validate_error,
    new_customer, new_inventory, new_boarding_cage, new_special_order,
    make_customer_headers, TEST_USERS,
    create_subscription_payload, create_reservation_payload,
)

SM = TEST_USERS["store_manager_headers"]


# ── combinatorial_formula (mode a): subscription monthly charge ──────────────

def test_subscription_charge_gold_premium_fresh(api):
    """PRD 3.7: "start from the tier base, which is 4,000 cents for STANDARD and
    7,000 cents for PREMIUM; add a per-bird component of 1,500 cents multiplied by
    bird_count; if fresh_feed is true, add a fresh surcharge of 2,500 cents; then apply
    the owning customer's club discount, read from their club_tier at creation time —
    a discount of 0 percent for NONE, 10 percent for SILVER, and 20 percent for GOLD —
    by multiplying the accumulated subtotal by one minus that discount fraction and
    rounding the product half up to a whole number of cents."

    Design: Difficulty/combinatorial_formula/subscription_charge_multi_input_mode_a
    """
    cust = new_customer(wallet_cents=10000, club_tier="GOLD")
    inv = new_inventory("FRESH", on_hand=10)
    sub = validate_success(api.create_subscription(
        create_subscription_payload(cust["id"], tier="PREMIUM", bird_count=2,
                                    fresh_feed=True, fresh_item_id=inv["id"]),
        make_customer_headers(cust["id"])), 201)
    # (7000 + 2*1500 + 2500) * 0.8 = 12500 * 0.8 = 10000
    assert sub["monthly_charge_cents"] == 10000
    assert sub["created_charge_cents"] == 10000


def test_subscription_charge_gold_debits_wallet(api):
    """PRD 3.7: "At creation the resulting monthly_charge_cents is snapshotted into
    created_charge_cents and that amount is debited from the customer's wallet, subject
    to the floor-zero wallet rule (ERR_INSUFFICIENT_WALLET) and the suspension rule
    (ERR_CUSTOMER_SUSPENDED)."

    Design: Difficulty/combinatorial_formula/subscription_charge_multi_input_mode_a
    """
    cust = new_customer(wallet_cents=10000, club_tier="GOLD")
    inv = new_inventory("FRESH", on_hand=10)
    validate_success(api.create_subscription(
        create_subscription_payload(cust["id"], tier="PREMIUM", bird_count=2,
                                    fresh_feed=True, fresh_item_id=inv["id"]),
        make_customer_headers(cust["id"])), 201)
    after = validate_success(api.get_customer(cust["id"], SM), 200)
    assert after["wallet_credit_cents"] == 0  # 10000 - 10000


# ── combinatorial_formula (mode b): per-line tax rounding then sum ────────────

def test_special_order_invoice_per_line_tax_rounding(api):
    """PRD 3.8: "For each line, the line subtotal is unit_price_cents multiplied by
    quantity; the line tax is that subtotal multiplied by the line's tax_rate, rounded
    half up to a whole number of cents; and the line's contribution is the subtotal plus
    the rounded tax. The invoice_total_cents is the sum of those per-line contributions
    across all lines."

    Design: Difficulty/combinatorial_formula/special_order_invoice_perline_rounding_mode_b
    """
    cust = new_customer(wallet_cents=5000)
    inv = new_inventory("DRY", on_hand=10)
    # Two lines: subtotal 740, tax 55.5 -> 56 each -> line 796 each -> total 1592.
    lines = [{"unit_price_cents": 740, "quantity": 1, "tax_rate": 0.075},
             {"unit_price_cents": 740, "quantity": 1, "tax_rate": 0.075}]
    order = new_special_order(cust["id"], inv["id"], build_qty=1, line_items=lines)
    assert order["invoice_total_cents"] == 1592


def test_special_order_invoice_rounds_before_summation(api):
    """PRD 3.8: "the tax for each line is rounded to whole cents individually, and only
    then are the lines summed — rounding per line before summation, not summing before
    rounding, because the two orders can yield different cent totals."

    Design: Difficulty/combinatorial_formula/special_order_invoice_perline_rounding_mode_b
    """
    cust = new_customer(wallet_cents=5000)
    inv = new_inventory("DRY", on_hand=10)
    lines = [{"unit_price_cents": 740, "quantity": 1, "tax_rate": 0.075},
             {"unit_price_cents": 740, "quantity": 1, "tax_rate": 0.075}]
    order = new_special_order(cust["id"], inv["id"], build_qty=1, line_items=lines)
    # Round-per-line-then-sum == 1592; sum-then-round would be 1591.
    assert order["invoice_total_cents"] == 1592
    assert order["invoice_total_cents"] != 1591


# ── corner: STANDARD tier, no club discount ──────────────────────────────────

def test_subscription_standard_no_club_discount(api):
    """PRD 3.7: "start from the tier base, which is 4,000 cents for STANDARD and 7,000
    cents for PREMIUM; add a per-bird component of 1,500 cents multiplied by bird_count"
    PRD 3.7: "a discount of 0 percent for NONE, 10 percent for SILVER, and 20 percent for GOLD"

    Design: Corner/calculations/subscription_standard_no_club_discount
    """
    cust = new_customer(wallet_cents=6000)
    sub = validate_success(api.create_subscription(
        create_subscription_payload(cust["id"], tier="STANDARD", bird_count=1),
        make_customer_headers(cust["id"])), 201)
    assert sub["monthly_charge_cents"] == 5500  # 4000 + 1500
    after = validate_success(api.get_customer(cust["id"], SM), 200)
    assert after["wallet_credit_cents"] == 500  # 6000 - 5500


# ── corner: boarding provisional minimum one night ───────────────────────────

def test_boarding_provisional_min_one_night(api):
    """PRD 3.5: "the number of nights is the difference between planned_check_out and
    planned_check_in divided by one day (86,400 seconds) and rounded up to the next whole
    night, with any partial day counting as a full night and a minimum of one night."

    Design: Corner/calculations/boarding_provisional_min_one_night
    """
    cust = new_customer()
    cage = new_boarding_cage(capacity=1, nightly_rate_cents=3000)
    validate_success(api.set_clock("2026-07-01T00:00:00Z", SM), 200)
    res = validate_success(api.create_reservation(
        create_reservation_payload(cust["id"], cage["id"],
                                   planned_check_in="2026-07-03T00:00:00Z",
                                   planned_check_out="2026-07-03T06:00:00Z"),
        make_customer_headers(cust["id"])), 201)
    assert res["provisional_cost_cents"] == 3000  # 6h partial day -> 1 night * 3000


# ── corner: immediate visibility of the creation wallet debit ────────────────

def test_subscription_creation_immediate_visibility(api):
    """PRD 3.7: "At creation the resulting monthly_charge_cents is snapshotted into
    created_charge_cents and that amount is debited from the customer's wallet, subject
    to the floor-zero wallet rule (ERR_INSUFFICIENT_WALLET) and the suspension rule
    (ERR_CUSTOMER_SUSPENDED)."

    Design: Corner/consistency_model/subscription_creation_immediate_visibility
    """
    cust = new_customer(wallet_cents=6000)
    validate_success(api.create_subscription(
        create_subscription_payload(cust["id"], tier="STANDARD", bird_count=1),
        make_customer_headers(cust["id"])), 201)
    fetched = validate_success(api.get_customer(cust["id"], SM), 200)
    assert fetched["wallet_credit_cents"] == 500  # 6000 - 5500, visible immediately


# ── corner: pay with insufficient wallet ─────────────────────────────────────

def test_pay_insufficient_wallet_rejected(api):
    """PRD 3.8: "requires the customer's wallet_credit_cents to be at least
    invoice_total_cents, else ERR_INSUFFICIENT_WALLET."
    PRD 2.6: "Any debit that would do so is rejected with ERR_INSUFFICIENT_WALLET
    (HTTP 402), and the balance is left untouched."

    Design: Corner/validations/pay_insufficient_wallet_rejected
    """
    cust = new_customer(wallet_cents=0)
    inv = new_inventory("DRY", on_hand=5)
    order = new_special_order(cust["id"], inv["id"], build_qty=1,
                              line_items=[{"unit_price_cents": 1000, "quantity": 1, "tax_rate": 0.0}])
    res = api.pay_order(order["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_INSUFFICIENT_WALLET", expected_status=402)
    after = validate_success(api.get_customer(cust["id"], SM), 200)
    assert after["wallet_credit_cents"] == 0
    order_after = validate_success(api.get_special_order(order["id"], SM), 200)
    assert order_after["payment_status"] == "UNPAID"
