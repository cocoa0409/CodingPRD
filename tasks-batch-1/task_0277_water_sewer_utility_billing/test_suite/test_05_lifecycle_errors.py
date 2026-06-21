"""Lifecycle precondition and invalid-transition errors across bills, reads,
cycles, and shutoff orders.

Translates Corner queue: state_machines + validations sections.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_scheduled_shutoff, setup_canonical_posted_bill,
    fixtures, factories, TEST_USERS, ApiErrorId,
)

CLERK = TEST_USERS["billing_clerk_headers"]
FIELDOPS = TEST_USERS["field_ops_headers"]


# ===========================================================================
# Bill lifecycle invalid transitions / preconditions
# ===========================================================================
def test_post_already_posted_bill_returns_invalid_state(api):
    """PRD §2.9: "Only then does the system evaluate state legality, namely whether
    the targeted resource is in a state from which the requested transition is
    defined (`ERR_INVALID_STATE`)"
    PRD §3.5: "When a `BillingClerk` posts a bill, advancing it from `DRAFT` to
    `POSTED`, the system finalizes all computed charge fields"

    Design: Corner/state_machines/post_bill_from_already_posted_returns_invalid_state
    """
    account, bill, rs, cycle = setup_canonical_posted_bill(potable=6000, irrigation=None)
    resp = api.post_bill(bill["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_duplicate_bill_same_account_cycle_returns_409(api):
    """PRD §3.4: "At most one non-`VOID` bill may exist for a given account and cycle
    pairing; a second attempt is rejected with `ERR_DUPLICATE_BILL`."

    Design: Corner/state_machines/duplicate_bill_same_account_cycle_returns_409
    """
    account, bill, rs, cycle, _, _ = fixtures.setup_canonical_draft_bill(potable=6000, irrigation=None)
    resp = api.create_bill(factories.bill_payload(account["id"], cycle["id"]), CLERK)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BILL.value)


def test_void_posted_bill_with_payment_returns_409(api):
    """PRD §3.5: "A `POSTED` bill may only be voided if no payment has yet been
    applied to it; an attempt to void a posted bill that already has an applied
    payment is rejected with `ERR_BILL_HAS_PAYMENT`."

    Design: Corner/state_machines/void_posted_bill_with_payment_returns_409
    """
    account, bill, rs, cycle = setup_canonical_posted_bill(potable=6000, irrigation=None)
    validate_success(
        api.create_payment(account["id"], factories.payment_payload(1000, method="ACH"), CLERK), 201)
    resp = api.void_bill(bill["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_BILL_HAS_PAYMENT.value)


def test_bill_on_closed_cycle_returns_409(api):
    """PRD §3.4: "Generation against a `CLOSED` cycle is rejected with
    `ERR_CYCLE_CLOSED`."

    Design: Corner/validations/bill_on_closed_cycle_returns_409
    """
    fixtures.set_clock("2026-02-20T00:00:00Z")
    rs = fixtures.create_rate_schedule()
    account = fixtures.create_account(rs["id"])
    meter = fixtures.create_meter(account["id"], "POTABLE", "P1")
    cycle = fixtures.create_cycle()
    fixtures.add_read(meter["id"], 0, "2026-01-01T00:00:00Z")
    fixtures.add_read(meter["id"], 6000, "2026-01-20T00:00:00Z")
    validate_success(api.close_billing_cycle(cycle["id"], CLERK))
    resp = api.create_bill(factories.bill_payload(account["id"], cycle["id"]), CLERK)
    validate_error(resp, ApiErrorId.ERR_CYCLE_CLOSED.value)


# ===========================================================================
# Meter read regression
# ===========================================================================
def test_meter_read_regression_returns_422(api):
    """PRD §3.2: "A read whose `reading_gallons` falls below the meter's prior
    chronological reading is rejected with `ERR_READ_REGRESSION` unless the read is
    a `MANUAL` rollover correction."

    Design: Corner/validations/meter_read_regression_returns_422
    """
    rs = fixtures.create_rate_schedule()
    account = fixtures.create_account(rs["id"])
    meter = fixtures.create_meter(account["id"], "POTABLE", "P1")
    validate_success(
        api.create_read(meter["id"], factories.read_payload(10000, "2026-01-01T00:00:00Z"), CLERK), 201)
    resp = api.create_read(
        meter["id"], factories.read_payload(3000, "2026-01-10T00:00:00Z", source="AMI"), CLERK)
    validate_error(resp, ApiErrorId.ERR_READ_REGRESSION.value)


# ===========================================================================
# Shutoff execute / reconnect preconditions
# ===========================================================================
def test_execute_before_scheduled_for_returns_not_due(api):
    """PRD §3.9: "Execution is permitted only when the order is `SCHEDULED`, the
    current server clock has reached or passed the order's `scheduled_for`
    (otherwise `ERR_SHUTOFF_NOT_DUE`)"

    Design: Corner/state_machines/execute_shutoff_before_scheduled_for_returns_not_due
    """
    account, bill, order, rs, cycle = setup_scheduled_shutoff(
        potable=30000, irrigation=None, scheduled_for="2026-03-10T00:00:00Z")
    fixtures.set_clock("2026-03-05T00:00:00Z")  # before scheduled_for
    resp = api.execute_shutoff_order(order["id"], FIELDOPS)
    validate_error(resp, ApiErrorId.ERR_SHUTOFF_NOT_DUE.value)


def test_reconnect_scheduled_order_returns_not_executed(api):
    """PRD §3.9: "A `FieldOps` operator reconnects an order that is in `EXECUTED`,
    moving it to `RECONNECTED`; reconnecting an order that is not `EXECUTED` is
    rejected with `ERR_NOT_EXECUTED`."

    Design: Corner/state_machines/reconnect_scheduled_order_returns_not_executed
    """
    account, bill, order, rs, cycle = setup_scheduled_shutoff(
        potable=30000, irrigation=None, scheduled_for="2026-03-10T00:00:00Z")
    resp = api.reconnect_shutoff_order(order["id"], FIELDOPS)
    validate_error(resp, ApiErrorId.ERR_NOT_EXECUTED.value)
