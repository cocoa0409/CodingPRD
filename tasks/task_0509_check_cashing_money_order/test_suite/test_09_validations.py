"""Breadth tests on posting-gate validations: OFAC block, fee-schedule rules,
embargo, risk ceiling, daily cash limit, recovery overpayment (PRD §2.8, §3.2,
§3.4, §3.6, §3.8, §3.9)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    create_money_order_payload, create_check_cash_payload, create_wire_payload,
    create_transaction_payload,
    setup_verified_customer_and_drawer, setup_verified_customer_drawer_and_schedule,
    setup_returned_check,
    create_customer, screen_customer, create_fee_schedule, open_drawer,
    recover_payload,
    make_teller_headers, make_store_manager_headers,
)

TELLER = make_teller_headers("teller-1")
MANAGER = make_store_manager_headers("manager-9")


def test_fee_schedule_required_for_check_cash(api):
    """PRD §3.4: "A check-cash posting requires a `fee_schedule_id` referencing an `active`
    schedule; for any other `txn_type` the `fee_schedule_id` must be null. A missing or
    inactive schedule on a check-cash, or a non-null schedule on any other type, is rejected
    with `ERR_FEE_SCHEDULE_INVALID`."

    Design: Corner/validations/fee_schedule_required_for_check_cash
    """
    cust, drawer = setup_verified_customer_and_drawer("C19", opening_float_cents=1000000)
    res = api.create_transaction(
        create_transaction_payload(cust["id"], drawer["id"], "CHECK_CASH", 100000,
                                   maker_account_risk="LOW"), TELLER)
    validate_error(res, ApiErrorId.ERR_FEE_SCHEDULE_INVALID, expected_status=422)


def test_fee_schedule_forbidden_for_non_check_cash(api):
    """PRD §3.4: "for any other `txn_type` the `fee_schedule_id` must be null. A missing or
    inactive schedule on a check-cash, or a non-null schedule on any other type, is rejected
    with `ERR_FEE_SCHEDULE_INVALID`."

    Design: Corner/validations/fee_schedule_forbidden_for_non_check_cash
    """
    cust, drawer, sched = setup_verified_customer_drawer_and_schedule(
        store_code="C20", opening_float_cents=1000000)
    res = api.create_transaction(
        create_transaction_payload(cust["id"], drawer["id"], "MONEY_ORDER", 50000,
                                   payee_name="R", fee_schedule_id=sched["id"]), TELLER)
    validate_error(res, ApiErrorId.ERR_FEE_SCHEDULE_INVALID, expected_status=422)


def test_embargoed_wire_destination_rejected(api):
    """PRD §3.6: "A wire whose `destination_country` is one of the embargoed set `CU`, `IR`,
    `KP`, or `SY` is rejected at posting with `ERR_EMBARGOED_DESTINATION`."

    Design: Corner/validations/embargoed_wire_destination_rejected
    """
    cust, drawer = setup_verified_customer_and_drawer("C21", opening_float_cents=1000000)
    res = api.create_transaction(
        create_wire_payload(cust["id"], drawer["id"], 100000,
                            destination_country="KP", beneficiary_name="B"), TELLER)
    validate_error(res, ApiErrorId.ERR_EMBARGOED_DESTINATION, expected_status=422)


def test_risk_ceiling_exceeded_standard_tier(api):
    """PRD §3.8: "A posting's `face_amount_cents` must not exceed the customer's
    per-transaction ceiling: 500000 cents for `STANDARD`, 200000 cents for `ELEVATED`, and
    50000 cents for `HIGH`. A face amount above the applicable ceiling is rejected with
    `ERR_RISK_CEILING_EXCEEDED`."

    STANDARD-tier (risk_score 0) MONEY_ORDER face=600000 > 500000 -> ERR_RISK_CEILING_EXCEEDED.

    Design: Corner/validations/risk_ceiling_exceeded_standard_tier
    """
    cust, drawer = setup_verified_customer_and_drawer("C22", opening_float_cents=2000000)
    res = api.create_transaction(
        create_money_order_payload(cust["id"], drawer["id"], 600000, "S"), TELLER)
    validate_error(res, ApiErrorId.ERR_RISK_CEILING_EXCEEDED, expected_status=422)


def test_daily_cash_limit_exceeded_check_cash(api):
    """PRD §3.8: "The projected cashed amount is the current `daily_cashed_amount_cents`
    plus the face amount for a check-cash posting ...; if that projected cashed amount would
    exceed the daily cash limit of 1000000 cents, a check-cash posting is rejected with
    `ERR_DAILY_LIMIT_EXCEEDED`."

    Five CHECK_CASH of 180000 (cashed 900000), then a CHECK_CASH face=200000 (projected
    1100000 > 1000000) on an OPEN drawer -> ERR_DAILY_LIMIT_EXCEEDED.

    Design: Corner/validations/daily_cash_limit_exceeded_check_cash
    """
    cust, drawer, sched = setup_verified_customer_drawer_and_schedule(
        store_code="C23", opening_float_cents=2000000)
    for _ in range(5):
        validate_success(api.create_transaction(
            create_check_cash_payload(cust["id"], drawer["id"], 180000, sched["id"], "LOW"),
            TELLER), 201)
    res = api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 200000, sched["id"], "LOW"),
        TELLER)
    validate_error(res, ApiErrorId.ERR_DAILY_LIMIT_EXCEEDED, expected_status=422)


def test_recovery_overpayment_rejected(api):
    """PRD §3.9: "an amount of 0 or less, or any amount that would overpay the remaining
    balance, is rejected with `ERR_RECOVERY_OVERPAYMENT` (overpayment is refused outright,
    not silently capped)."

    Fresh ReturnedItem total_owed 102500 (remaining 102500); recover 102501 -> rejected.

    Design: Corner/validations/recovery_overpayment_rejected
    """
    cust, drawer, sched, txn, ri = setup_returned_check(
        store_code="C24", face_amount_cents=100000, teller_id="teller-1")
    res = api.recover_returned_item(ri["id"], recover_payload(102501), TELLER)
    validate_error(res, ApiErrorId.ERR_RECOVERY_OVERPAYMENT, expected_status=422)


def test_inactive_fee_schedule_rejected(api):
    """PRD §3.4: "A check-cash posting requires a `fee_schedule_id` referencing an `active`
    schedule ...  A missing or inactive schedule on a check-cash ... is rejected with
    `ERR_FEE_SCHEDULE_INVALID`."

    Design: Corner/validations/inactive_fee_schedule_rejected
    """
    cust, drawer = setup_verified_customer_and_drawer("C25", opening_float_cents=1000000)
    sched = create_fee_schedule(check_type="PERSONAL", base_fee_cents=500,
                                percent_rate_bps=300, tier_breakpoint_cents=100000,
                                high_percent_rate_bps=400, max_fee_cents=10000, active=False)
    res = api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 50000, sched["id"], "LOW"),
        TELLER)
    validate_error(res, ApiErrorId.ERR_FEE_SCHEDULE_INVALID, expected_status=422)
