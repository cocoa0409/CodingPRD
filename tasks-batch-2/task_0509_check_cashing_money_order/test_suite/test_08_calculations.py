"""Breadth tests on fee/aggregation calculations and the velocity-window rollover
(PRD §3.2, §3.5, §3.8)."""
import pytest
from test_helpers import (
    api_client, validate_success,
    create_check_cash_payload, create_wire_payload, create_money_order_payload,
    create_prepaid_load_payload,
    setup_verified_customer_and_drawer, setup_verified_customer_drawer_and_schedule,
    create_fee_schedule, post_money_order, set_clock,
    make_teller_headers, make_store_manager_headers,
)

TELLER = make_teller_headers("teller-1")
MANAGER = make_store_manager_headers("manager-9")


def test_check_cash_fee_min_cap_applied(api):
    """PRD §3.2: "The raw fee is the base plus the percentage portion; the final `fee_cents`
    is the smaller of that raw fee and the `max_fee_cents` ceiling."

    base=199, pr=150, bp=199999, max=2500, face=199000 (<= bp):
    raw = 199 + floor(199000*150/10000)=199+2985=3184, capped at 2500.

    Design: Corner/calculations/check_cash_fee_min_cap_applied
    """
    cust, drawer, sched = setup_verified_customer_drawer_and_schedule(
        store_code="C13", opening_float_cents=1000000,
        schedule_overrides={
            "check_type": "PERSONAL", "base_fee_cents": 199, "percent_rate_bps": 150,
            "tier_breakpoint_cents": 199999, "high_percent_rate_bps": 275,
            "max_fee_cents": 2500, "active": True,
        })
    txn = validate_success(api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 199000, sched["id"], "LOW"),
        TELLER), 201)
    assert txn["fee_cents"] == 2500, f"expected capped fee 2500, got {txn['fee_cents']}"


def test_wire_fee_uncapped_correct_result(api):
    """PRD §3.2: "For a `WIRE`, the fee is 1500 cents plus the face multiplied by 100 basis
    points divided by 10000 (floored), with no cap."

    face=300000 -> 1500 + floor(300000*100/10000) = 1500 + 3000 = 4500.

    Design: Corner/calculations/wire_fee_uncapped_correct_result
    """
    cust, drawer = setup_verified_customer_and_drawer("C14", opening_float_cents=1000000)
    txn = validate_success(api.create_transaction(
        create_wire_payload(cust["id"], drawer["id"], 300000,
                            destination_country="MX", beneficiary_name="Beneficiary"),
        TELLER), 201)
    assert txn["fee_cents"] == 4500, f"expected wire fee 4500, got {txn['fee_cents']}"


def test_drawer_expected_cash_aggregation_two_txns(api):
    """PRD §3.5: "Expected cash equals the opening float, minus the total of (face minus
    fee) across all posted check-cash transactions, plus the total of (face plus fee)
    across all posted non-check-cash transactions."

    opening 1000000 - (100000-1099) + (50000+349) = 1000000 - 98901 + 50349 = 951448.

    Design: Corner/calculations/drawer_expected_cash_aggregation_two_txns
    """
    cust, drawer, sched = setup_verified_customer_drawer_and_schedule(
        store_code="C15", opening_float_cents=1000000)
    validate_success(api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 100000, sched["id"], "LOW"),
        TELLER), 201)
    validate_success(api.create_transaction(
        create_money_order_payload(cust["id"], drawer["id"], 50000, "Acme"), TELLER), 201)
    drawer_after = validate_success(api.get_cash_drawer(drawer["id"], MANAGER), 200)
    assert drawer_after["expected_cash_cents"] == 951448


def test_prepaid_flat_floor_when_pct_smaller(api):
    """PRD §3.2: "For a `PREPAID_LOAD`, the fee is the greater of 395 cents and the face
    multiplied by 30 basis points divided by 10000 (floored)."

    face=10000 -> max(395, floor(10000*30/10000)=30) = 395 (flat branch wins).

    Design: Corner/calculations/prepaid_flat_floor_when_pct_smaller
    """
    cust, drawer = setup_verified_customer_and_drawer("C16", opening_float_cents=1000000)
    txn = validate_success(api.create_transaction(
        create_prepaid_load_payload(cust["id"], drawer["id"], 10000, card_last_four="9999"),
        TELLER), 201)
    assert txn["fee_cents"] == 395, f"expected flat prepaid fee 395, got {txn['fee_cents']}"


def test_velocity_window_rollover_resets_counters(api):
    """PRD §3.8: "if the current clock time is at or after `limit_window_opened_at` plus 24
    hours, the window rolls — `limit_window_opened_at` is reset to the current time and both
    `daily_transaction_count` and `daily_cashed_amount_cents` are reset to 0. The boundary
    is half-open: a posting whose clock time falls exactly at the 24-hour mark rolls the
    window".
    PRD §2.4: timestamps are "ISO 8601 UTC with three fractional digits".

    One posting at 08:00:00Z (count 1), advance to exactly +24h, post again -> count resets
    to 1 and limit_window_opened_at == 2026-05-02T08:00:00.000Z.

    Design: Corner/calculations/velocity_window_rollover_resets_counters
    """
    set_clock("2026-05-01T08:00:00Z")
    cust, drawer = setup_verified_customer_and_drawer("C17", opening_float_cents=1000000)
    post_money_order(cust["id"], drawer["id"], 1000, payee_name="P1")
    set_clock("2026-05-02T08:00:00Z")
    validate_success(api.create_transaction(
        create_money_order_payload(cust["id"], drawer["id"], 1000, "P2"), TELLER), 201)
    cust_after = validate_success(api.get_customer(cust["id"], TELLER), 200)
    assert cust_after["daily_transaction_count"] == 1
    assert cust_after["limit_window_opened_at"] == "2026-05-02T08:00:00.000Z"
