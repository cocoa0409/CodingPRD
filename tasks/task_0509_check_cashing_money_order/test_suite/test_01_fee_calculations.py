"""Fee calculation depth tests: check-cash tiered pricing, per-leg flooring,
service-fee modes, and the hold-threshold boundary (PRD §3.2, §3.5)."""
import pytest
from test_helpers import (
    api_client, validate_success,
    create_check_cash_payload, create_prepaid_load_payload,
    setup_verified_customer_and_drawer, setup_verified_customer_drawer_and_schedule,
    create_payroll_divergent_schedule, get_check_item_for_transaction,
    make_teller_headers,
)

TELLER = make_teller_headers("teller-1")


def test_check_cash_fee_float_gross_on_full_face(api):
    """PRD §3.2: "Begin with the flat `base_fee_cents`. Then compute the percentage
    portion against the check's face amount. If the face amount is at or below the
    `tier_breakpoint_cents`, the percentage portion is the face amount multiplied by
    `percent_rate_bps`, divided by 10000 with integer floor division."
    PRD §3.2: "The check-cash fee is charged on the full check face and is never
    reduced by a later return."

    With base=99, percent_rate_bps=100, breakpoint=500000, face=100000 (<= breakpoint):
    pct = floor(100000*100/10000) = 1000; fee = 99 + 1000 = 1099.

    Design: Difficulty/dual_variant_calc/check_cash_fee_float_gross_on_full_face
    """
    cust, drawer, sched = setup_verified_customer_drawer_and_schedule(
        store_code="S1", opening_float_cents=1000000,
        schedule_overrides={
            "check_type": "GOVERNMENT", "base_fee_cents": 99, "percent_rate_bps": 100,
            "tier_breakpoint_cents": 500000, "high_percent_rate_bps": 200,
            "max_fee_cents": 50000, "active": True,
        })
    res = api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 100000, sched["id"], "LOW"),
        TELLER)
    txn = validate_success(res, 201)
    assert txn["fee_cents"] == 1099, f"expected fee 1099, got {txn['fee_cents']}"
    assert txn["lifecycle_state"] == "POSTED"
    assert txn["settlement_state"] == "SETTLED"


def test_check_cash_fee_per_leg_floor_then_sum(api):
    """PRD §3.2: "If the face amount is above the breakpoint, the percentage portion is
    the sum of two legs computed separately: a low leg equal to the breakpoint multiplied
    by `percent_rate_bps` divided by 10000 (floored), plus a high leg equal to the excess
    of the face over the breakpoint multiplied by `high_percent_rate_bps` divided by 10000
    (floored). Each leg is floored to whole cents on its own before the two are added —
    this per-leg flooring is the binding precision rule."

    base=199, pr=150, bp=199999, hpr=275, face=250001:
    low = floor(199999*150/10000) = 2999; high = floor((250001-199999)*275/10000) = 1375;
    fee = 199 + 2999 + 1375 = 4573 (sum-then-floor would give 4574).

    Design: Difficulty/combinatorial_formula/check_cash_fee_per_leg_floor_then_sum_mode_b
    """
    cust, drawer = setup_verified_customer_and_drawer("S3", opening_float_cents=2000000)
    sched = create_payroll_divergent_schedule()
    res = api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 250001, sched["id"], "LOW"),
        TELLER)
    txn = validate_success(res, 201)
    assert txn["fee_cents"] == 4573, f"expected per-leg-floored fee 4573, got {txn['fee_cents']}"
    assert txn["lifecycle_state"] == "POSTED"


def test_prepaid_load_fee_greater_of_pct_wins(api):
    """PRD §3.2: "For a `PREPAID_LOAD`, the fee is the greater of 395 cents and the face
    multiplied by 30 basis points divided by 10000 (floored)."

    face=200000: pct leg = floor(200000*30/10000) = 600 > 395 flat -> fee = 600.

    Design: Difficulty/combinatorial_formula/service_fee_greater_of_and_cap_mode_a
    """
    cust, drawer = setup_verified_customer_and_drawer("S4", opening_float_cents=1000000)
    res = api.create_transaction(
        create_prepaid_load_payload(cust["id"], drawer["id"], 200000, card_last_four="4242"),
        TELLER)
    txn = validate_success(res, 201)
    assert txn["fee_cents"] == 600, f"expected greater-of fee 600, got {txn['fee_cents']}"
    assert txn["settlement_state"] == "SETTLED"


def test_hold_threshold_exact_ge_boundary_holds(api):
    """PRD §3.5: "A check is placed on hold — moving `VERIFYING → RISK_HELD` — if any of
    three conditions is met: the face amount is at least 300000 cents (that is, $3,000 or
    more), or the maker's account risk is `HIGH`, or the customer's daily transaction count
    has already reached 8 within the current window."
    PRD §3.5: "When a check is held, no cash moves: the parent transaction stays in
    `lifecycle_state` `DRAFT`".

    face == 300000 exactly equals the threshold; >= is inclusive so it MUST hold with
    hold_reason AMOUNT_THRESHOLD.

    Design: Difficulty/boundary_precision_check/hold_threshold_exact_ge_boundary_on_post
    """
    cust, drawer = setup_verified_customer_and_drawer("S11", opening_float_cents=2000000)
    sched = create_payroll_divergent_schedule()
    res = api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 300000, sched["id"], "LOW"),
        TELLER)
    txn = validate_success(res, 201)
    check = get_check_item_for_transaction(txn["id"])
    assert check["verification_state"] == "RISK_HELD"
    assert check["hold_reason"] == "AMOUNT_THRESHOLD"
    fetched = validate_success(api.get_transaction(txn["id"], TELLER), 200)
    assert fetched["lifecycle_state"] == "DRAFT"
