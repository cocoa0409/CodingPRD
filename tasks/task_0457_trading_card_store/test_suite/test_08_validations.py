"""Single-failure validation scenarios: banned-customer check-in, unpaid check-in,
grade out of range, zero-quantity line, zero-capacity open, full event, reserved
inventory on grading send, insufficient store credit on pay.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_customer, create_inventory_item, create_open_event,
    create_registration, create_paid_registration, create_submitted_buylist,
    create_inventory_item_with_stock, create_at_grader_submission,
    create_event, set_clock,
    create_buylist_submission_payload, create_buylist_line_payload,
    create_grading_submission_payload,
    ApiErrorId, TEST_USERS, make_customer_headers,
)

SM = TEST_USERS["store_manager_headers"]


def test_check_in_banned_customer_rejected(api):
    """PRD §3.4: "Check-in requires that the registration's `payment_status` is
    `PAID` (otherwise `ERR_REGISTRATION_NOT_PAID`), that the customer's `status` is
    `ACTIVE` (otherwise `ERR_CUSTOMER_BANNED`), and that the parent event is `OPEN`
    or `IN_PROGRESS` (otherwise `ERR_INVALID_STATE`)."

    Design: Corner/validations/register_banned_customer_check_in_blocked
    """
    set_clock("2026-06-01T00:00:00Z")
    cust = create_customer("Ban Cust", "ban@x.com", credit_cents=5000)
    ev = create_open_event(title="Ban Event", format="STANDARD",
                           starts_at="2026-06-10T00:00:00Z",
                           ends_at="2026-06-10T04:00:00Z", capacity=8,
                           entry_fee_cents=1000)
    reg = create_paid_registration(ev, cust)
    validate_success(api.ban_customer(cust["id"], SM), 200)
    res = api.check_in_registration(reg["id"], SM)
    validate_error(res, ApiErrorId.ERR_CUSTOMER_BANNED)


def test_check_in_unpaid_registration_rejected(api):
    """PRD §3.4: "Check-in requires that the registration's `payment_status` is
    `PAID` (otherwise `ERR_REGISTRATION_NOT_PAID`)"

    Design: Corner/validations/check_in_unpaid_registration_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    cust = create_customer("Unpaid Cust", "unpaid@x.com")
    ev = create_open_event(title="Unpaid Event", format="STANDARD",
                           starts_at="2026-06-10T00:00:00Z",
                           ends_at="2026-06-10T04:00:00Z", capacity=8,
                           entry_fee_cents=1000)
    reg = create_registration(ev, cust)  # UNPAID
    res = api.check_in_registration(reg["id"], SM)
    validate_error(res, ApiErrorId.ERR_REGISTRATION_NOT_PAID)


def test_grade_out_of_range_rejected(api):
    """PRD §3.6: "When the body provides an `assigned_grade`, the result must lie
    between 1 and 10 inclusive (otherwise `ERR_INVALID_GRADE`)"

    Design: Corner/validations/invalid_grade_out_of_range
    """
    item, owner = create_inventory_item_with_stock(market_price_cents=4000, quantity=1)
    gs = create_at_grader_submission(owner, item, declared_value_cents=5000,
                                     service_tier="ECONOMY")
    res = api.return_grading_result(gs["id"], {"assigned_grade": 11}, SM)
    validate_error(res, ApiErrorId.ERR_INVALID_GRADE)


def test_zero_quantity_buylist_line_rejected(api):
    """PRD §3.2: "the `inventory_item_id` the card maps to, and a `quantity` of at
    least 1"
    PRD §2.9: "quantity-minimum checks then fail with `ERR_INVALID_QUANTITY` (HTTP
    422)"

    Design: Corner/validations/buylist_line_zero_quantity_rejected
    """
    cust = create_customer("ZQ Cust", "zq@x.com")
    item = create_inventory_item(title="ZQ Card", market_price_cents=500)
    cust_h = make_customer_headers(cust["id"])
    sub = get_success_data(api.create_buylist_submission(
        create_buylist_submission_payload(cust["id"], "CASH"), cust_h))
    res = api.create_buylist_line(
        create_buylist_line_payload(sub["id"], item["id"], quantity=0), cust_h)
    validate_error(res, ApiErrorId.ERR_INVALID_QUANTITY)


def test_open_zero_capacity_event_rejected(api):
    """PRD §3.5: "Opening an event for registration is a store-manager action that
    moves it from `SCHEDULED` to `OPEN`. It requires the event's `capacity` to be at
    least 1 (otherwise `ERR_INVALID_EVENT_CAPACITY`)"

    Design: Corner/validations/open_event_zero_capacity_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    ev = create_event(title="Zero Cap", format="DRAFT",
                      starts_at="2026-06-10T00:00:00Z",
                      ends_at="2026-06-10T03:00:00Z", capacity=0,
                      entry_fee_cents=1000)
    res = api.open_event(ev["id"], SM)
    validate_error(res, ApiErrorId.ERR_INVALID_EVENT_CAPACITY)


def test_register_full_event_rejected(api):
    """PRD §3.4: "Registration may not be created if it would push the event's
    seated/registered count past `capacity`, which fails with `ERR_EVENT_FULL`."

    Design: Corner/validations/register_full_event_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    ca = create_customer("Full A", "fa@x.com")
    cb = create_customer("Full B", "fb@x.com")
    ev = create_open_event(title="One Seat", format="STANDARD",
                           starts_at="2026-06-10T00:00:00Z",
                           ends_at="2026-06-10T04:00:00Z", capacity=1,
                           entry_fee_cents=1000)
    create_registration(ev, ca)
    res = api.create_registration(
        {"event_id": ev["id"], "customer_id": cb["id"]},
        make_customer_headers(cb["id"]))
    validate_error(res, ApiErrorId.ERR_EVENT_FULL)


def test_send_grading_with_no_stock_rejected(api):
    """PRD §3.6: "Sending the card to the grader is defined only from `INTAKE`
    (otherwise `ERR_INVALID_STATE`) and requires that holding one unit will not
    over-commit inventory: subtracting one from the item's `quantity_on_hand` must
    still leave it at or above the item's `quantity_reserved`, or the send is
    rejected with `ERR_INVENTORY_RESERVED`."

    Design: Corner/validations/send_grading_inventory_reserved_blocked
    """
    cust = create_customer("NoStock Cust", "nostock@x.com")
    item = create_inventory_item(title="NoStock Card", market_price_cents=4000)
    # Item never bought in: quantity_on_hand = 0, so on_hand - 1 < reserved.
    gs = get_success_data(api.create_grading_submission(
        create_grading_submission_payload(cust["id"], item["id"],
                                          declared_value_cents=5000,
                                          service_tier="ECONOMY"), SM))
    res = api.send_grading_submission(gs["id"], SM)
    validate_error(res, ApiErrorId.ERR_INVENTORY_RESERVED)


def test_pay_insufficient_store_credit_rejected(api):
    """PRD §3.4: "the customer's `store_credit_balance_cents` must be at least the
    registration's `quoted_fee_cents`, otherwise it fails with
    `ERR_INSUFFICIENT_STORE_CREDIT`."

    Design: Corner/validations/pay_insufficient_store_credit
    """
    set_clock("2026-06-01T00:00:00Z")
    cust = create_customer("Low Cust", "low@x.com", credit_cents=1000)
    ev = create_open_event(title="Low Event", format="STANDARD",
                           starts_at="2026-06-10T00:00:00Z",
                           ends_at="2026-06-10T04:00:00Z", capacity=8,
                           entry_fee_cents=2000)
    reg = create_registration(ev, cust)  # quoted 2000, balance only 1000
    res = api.pay_registration(reg["id"], make_customer_headers(cust["id"]))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_STORE_CREDIT)
