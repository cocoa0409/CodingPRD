"""Estimate/final pricing, deposit calculation, and the credit/loyalty waterfall.

Every test builds its own catalog and order from scratch; the server starts
against an empty database before each test.
"""
from test_helpers import (
    validate_success,
    ApiErrorId,
    make_customer_headers,
    balance_payment_payload,
    line_payload,
)
import test_helpers.fixtures as fx


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula
# ---------------------------------------------------------------------------
def test_deposit_complex_bake_uses_sixty_percent_ratio(api):
    """PRD 3.5: "If the product is a complex bake (its `tier_levels` is 3 or more),
    raise the ratio to whichever is larger of the current ratio and 0.60 - so a
    complex bake always demands at least 60%, and a complex *peak* bake also lands
    at 0.60."
    PRD 3.5: "Multiply the estimate total by the resulting ratio and round half-up
    to whole cents."

    Design: Difficulty/combinatorial_formula/deposit_calc_three_input_nonlinear_selection
    """
    order, customer, product, pday = fx.setup_draft_order(
        product_overrides={"name": "Tiered Wedding", "base_price_cents": 30000,
                           "base_lead_days": 5, "tier_levels": 3},
        pday_overrides={"production_date": "2026-06-25", "is_peak": False,
                        "order_cutoff_at": "2026-06-18T00:00:00Z"},
    )
    fx.add_line(order, customer, units=1)
    headers = make_customer_headers(customer["id"])
    data = validate_success(api.quote_order(order["id"], {}, headers), 200)
    assert data["estimate_total_cents"] == 30000, data
    assert data["deposit_due_cents"] == 18000, data
    assert data["balance_due_cents"] == 12000, data


def test_deposit_standard_bake_uses_thirty_percent_ratio(api):
    """PRD 3.5: "Begin with a base ratio of 0.30." PRD 3.5: "Multiply the estimate
    total by the resulting ratio and round half-up to whole cents."

    A non-peak, single-tier 30000 estimate deposits 30% = 9000, distinct from the
    60% complex ratio.

    Design: Difficulty/combinatorial_formula/deposit_calc_three_input_nonlinear_selection
    """
    order, customer, product, pday = fx.setup_draft_order(
        product_overrides={"name": "Plain", "base_price_cents": 30000, "tier_levels": 1},
    )
    fx.add_line(order, customer, units=1)
    headers = make_customer_headers(customer["id"])
    data = validate_success(api.quote_order(order["id"], {}, headers), 200)
    assert data["estimate_total_cents"] == 30000, data
    assert data["deposit_due_cents"] == 9000, data
    assert data["balance_due_cents"] == 21000, data


def test_peak_surcharge_mid_tier_evaluation_order(api):
    """PRD 3.5: "when the subtotal is at least 20000 but below 50000 cents the
    surcharge is the subtotal multiplied by 0.10, rounded half-up to whole cents".
    PRD 3.5: "`estimate_total_cents` is the lines subtotal plus `peak_surcharge_cents`."

    Subtotal 23000 -> 10% = 2300 -> total 25300, then a 50% peak deposit = 12650.

    Design: Difficulty/combinatorial_formula/peak_surcharge_circular_eval_order
    """
    order, customer, product, pday = fx.setup_draft_order(
        product_overrides={"name": "Peak Round", "base_price_cents": 10000,
                           "allowed_option_codes": ["SPRINKLES"]},
        pday_overrides={"is_peak": True},
        options=[("SPRINKLES", 1500)],
    )
    fx.add_line(order, customer, units=2, selected_option_codes=["SPRINKLES"])
    headers = make_customer_headers(customer["id"])
    data = validate_success(api.quote_order(order["id"], {}, headers), 200)
    assert data["peak_surcharge_cents"] == 2300, data
    assert data["estimate_total_cents"] == 25300, data
    assert data["deposit_due_cents"] == 12650, data


def test_peak_surcharge_zero_on_non_peak_day(api):
    """PRD 3.5: "If the order's production day is not a peak day, the peak surcharge
    is 0."

    Design: Difficulty/combinatorial_formula/peak_surcharge_circular_eval_order
    """
    order, customer, product, pday = fx.setup_draft_order(
        product_overrides={"name": "NonPeak Round", "base_price_cents": 10000,
                           "allowed_option_codes": ["SPRINKLES"]},
        pday_overrides={"is_peak": False},
        options=[("SPRINKLES", 1500)],
    )
    fx.add_line(order, customer, units=2, selected_option_codes=["SPRINKLES"])
    headers = make_customer_headers(customer["id"])
    data = validate_success(api.quote_order(order["id"], {}, headers), 200)
    assert data["peak_surcharge_cents"] == 0, data
    assert data["estimate_total_cents"] == 23000, data


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc (estimate vs final pricing divergence)
# ---------------------------------------------------------------------------
def test_final_total_diverges_from_estimate_after_changes(api):
    """PRD 3.9: "If the lines were edited during a `CHANGES_REQUESTED` loop, the
    final total diverges from the estimate, and from this point the balance is
    reconciled off the final total, not the stale estimate."
    PRD 3.9: "approval recomputes `balance_due_cents` as `final_total_cents` minus
    the sum of the captured deposit amount."

    Estimate locks at 23000 (deposit 6900); after editing to 3 units
    [SPRINKLES, GOLD_LEAF] the final total is 49500 and balance 49500-6900=42600.

    Design: Difficulty/dual_variant_calc/order_pricing_estimate_vs_final_divergence
    """
    order, customer, product, pday = fx.setup_draft_order(
        product_overrides={"name": "Vanilla Round", "base_price_cents": 10000,
                           "allowed_option_codes": ["SPRINKLES", "GOLD_LEAF"]},
        options=[("SPRINKLES", 1500), ("GOLD_LEAF", 5000)],
    )
    headers = make_customer_headers(customer["id"])
    line = fx.add_line(order, customer, units=2, selected_option_codes=["SPRINKLES"])
    quoted = validate_success(api.quote_order(order["id"], {}, headers), 200)
    assert quoted["estimate_total_cents"] == 23000, quoted

    fx.pay_deposit(order, customer)
    proof1 = fx.post_proof(order, "proof-r1")
    fx.request_changes(order, proof1, customer, "add gold leaf")
    validate_success(
        api.edit_line(order["id"], line["id"],
                      {"units": 3, "selected_option_codes": ["SPRINKLES", "GOLD_LEAF"]},
                      headers), 200)
    proof2 = fx.post_proof(order, "proof-r2")
    validate_success(api.approve_proof(order["id"], proof2["id"], {}, headers), 200)

    final = validate_success(api.get_order(order["id"], headers), 200)
    assert final["estimate_total_cents"] == 23000, final
    assert final["final_total_cents"] == 49500, final
    assert final["final_total_cents"] != final["estimate_total_cents"], final
    assert final["balance_due_cents"] == 42600, final


def test_final_total_matches_estimate_when_lines_unchanged(api):
    """PRD 3.9: "If the lines were never touched after quoting, the final total
    equals the estimate total and the delta is zero."

    Design: Difficulty/dual_variant_calc/order_pricing_estimate_vs_final_divergence
    """
    order, customer, proof, product, pday = fx.setup_proof_approved_order(units=2)
    headers = make_customer_headers(customer["id"])
    data = validate_success(api.get_order(order["id"], headers), 200)
    assert data["estimate_total_cents"] == 20000, data
    assert data["final_total_cents"] == 20000, data
    assert data["final_total_cents"] == data["estimate_total_cents"], data


# ---------------------------------------------------------------------------
# Queue B: calculations — balance capture waterfall and loyalty
# ---------------------------------------------------------------------------
def test_gross_balance_capture_no_credit(api):
    """PRD 3.10: "When no credit is applied (`applied_credit_cents` is zero), the
    fresh tender equals the whole gross balance and lifetime spend rises by that
    full amount".
    PRD 3.2: "a customer is `STANDARD` while `lifetime_spend_cents` is below 50000".

    Design: Corner/calculations/gross_balance_capture_no_credit
    """
    order, customer, proof, product, pday = fx.setup_proof_approved_order(units=2)
    headers = make_customer_headers(customer["id"])
    fresh = validate_success(api.get_order(order["id"], headers), 200)
    validate_success(
        api.post_balance_payment(order["id"], balance_payment_payload(fresh["version"], 0), headers), 201)

    order_after = validate_success(api.get_order(order["id"], headers), 200)
    assert order_after["payment_status"] == "PAID_IN_FULL", order_after
    assert order_after["balance_due_cents"] == 0, order_after

    cust_after = validate_success(api.get_customer(customer["id"], headers), 200)
    assert cust_after["lifetime_spend_cents"] == 20000, cust_after
    assert cust_after["loyalty_tier"] == "STANDARD", cust_after


def test_credit_offset_capture_excludes_credit_from_loyalty(api):
    """PRD 3.10: "The credit actually applied, `credit_applied_cents`, is the
    smallest of three quantities: the `applied_credit_cents` the customer elected,
    the customer's available `store_credit_cents`, and the gross balance."
    PRD 3.10: "The customer's `lifetime_spend_cents` increases by the fresh tender
    only - store credit spent does not count toward loyalty".

    With 5000 credit on a 14000 balance: credit_applied 5000, fresh 9000,
    lifetime 6000+9000=15000, store credit drained to 0.

    Design: Corner/calculations/credit_offset_capture_loyalty_excludes_credit
    """
    order, customer, proof, product, pday = fx.setup_proof_approved_order(units=2)
    fx.grant_credit(customer["id"], 5000, "goodwill")
    headers = make_customer_headers(customer["id"])
    fresh = validate_success(api.get_order(order["id"], headers), 200)
    payment = validate_success(
        api.post_balance_payment(order["id"], balance_payment_payload(fresh["version"], 5000), headers), 201)
    assert payment["credit_applied_cents"] == 5000, payment
    assert payment["amount_cents"] == 9000, payment

    cust_after = validate_success(api.get_customer(customer["id"], headers), 200)
    assert cust_after["store_credit_cents"] == 0, cust_after
    assert cust_after["lifetime_spend_cents"] == 15000, cust_after


def test_loyalty_promotes_to_silver_at_threshold(api):
    """PRD 3.2: "`SILVER` while it is from 50000 through 149999 inclusive".
    PRD 3.10: "the fresh tender equals the whole gross balance and lifetime spend
    rises by that full amount".

    lifetime_spend reaching exactly 50000 promotes the tier to SILVER.

    Design: Corner/calculations/loyalty_tier_promotes_at_silver_threshold
    """
    order, customer, proof, product, pday = fx.setup_proof_approved_order(
        units=2, product_overrides={"name": "Silver", "base_price_cents": 25000})
    headers = make_customer_headers(customer["id"])
    fresh = validate_success(api.get_order(order["id"], headers), 200)
    validate_success(
        api.post_balance_payment(order["id"], balance_payment_payload(fresh["version"], 0), headers), 201)

    cust_after = validate_success(api.get_customer(customer["id"], headers), 200)
    assert cust_after["lifetime_spend_cents"] == 50000, cust_after
    assert cust_after["loyalty_tier"] == "SILVER", cust_after


# ---------------------------------------------------------------------------
# Queue B: consistency_model — immediate recompute
# ---------------------------------------------------------------------------
def test_line_add_recomputes_estimate_immediately(api):
    """PRD 3.3: "When a line is added, edited, or removed while the order is
    `QUOTED`, the estimate and deposit are recomputed (see Section 3.5)".

    Adding a second unit-1 line to a QUOTED order (estimate 10000) takes the
    estimate to 20000 and the deposit to 6000, visible on the next read.

    Design: Corner/consistency_model/line_add_recomputes_order_estimate_immediately
    """
    order, customer, product, pday = fx.setup_quoted_order(units=1)
    headers = make_customer_headers(customer["id"])
    validate_success(api.add_line(order["id"], line_payload(units=1), headers), 201)
    data = validate_success(api.get_order(order["id"], headers), 200)
    assert data["estimate_total_cents"] == 20000, data
    assert data["deposit_due_cents"] == 6000, data
