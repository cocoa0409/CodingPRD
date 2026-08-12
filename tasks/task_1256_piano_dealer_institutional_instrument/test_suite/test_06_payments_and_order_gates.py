"""Payment gates, validation priority, and referenced-object state rules (PRD §2.8, §3.4, §3.5)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_customer, create_instrument, create_available_instrument,
    create_order, order_line, create_order_payload, post_payment, pay_order_in_full,
    get_order, get_instrument,
    create_offered_appraisal, create_delivery_crew, create_delivery_job_payload,
    create_bid, submit_bid, bid_line,
    TEST_USERS,
)

ASSOCIATE = TEST_USERS["sales_associate_headers"]
COORDINATOR = TEST_USERS["service_coordinator_headers"]


def _paid_order_515(api, serial="SN-O-1"):
    customer = create_customer(full_name="Oliver Overpay", email="oliver@x.com")
    instrument = create_available_instrument(
        serial_number=serial, category="DIGITAL", manufacturer="Roland", model="FP90",
        year_built=2024, list_price_cents=500_000, floor_price_cents=400_000)
    order = create_order(customer["id"], [order_line(instrument["id"], 500_000)])
    assert order["total_cents"] == 515_000
    return customer, instrument, pay_order_in_full(order)


def test_payment_on_settled_order_reports_state_error(api):
    """PRD §3.5: "Posting is permitted only while the order is `UNPAID` or `DEPOSIT_PAID`;
    against any later payment state the posting is rejected with `ERR_ORDER_NOT_PAYABLE`."
    PRD §2.8: "When a request violates several rules at once, the rejection it receives is
    determined by a fixed priority order, evaluated as follows." with "Fifth, state
    preconditions" ahead of "Tenth and last, money rules: overpayment (`ERR_OVERPAYMENT`,
    422), bid floor violations (`ERR_BID_BELOW_FLOOR`, 422), and credit-limit violations
    (`ERR_CREDIT_LIMIT_EXCEEDED`, 422)."
    (A 1-cent payment on a PAID_IN_FULL order violates both the state gate and the money
    gate; the state error wins.)

    Design: Difficulty/priority_pair_validation_conflict/payment_state_beats_overpayment_fiscal
    """
    _, _, order = _paid_order_515(api)
    res = api.post_payment(order["id"], {"amount_cents": 1, "method": "CARD"}, ASSOCIATE)
    validate_error(res, "ERR_ORDER_NOT_PAYABLE")


def test_payment_on_settled_order_leaves_state_untouched(api):
    """PRD §3.5: "Posting is permitted only while the order is `UNPAID` or `DEPOSIT_PAID`;
    against any later payment state the posting is rejected with `ERR_ORDER_NOT_PAYABLE`."
    PRD §3.4: "`amount_paid_cents` starts at zero; and `balance_cents` is always the total
    minus the amount paid."

    Design: Difficulty/priority_pair_validation_conflict/payment_state_beats_overpayment_fiscal
    """
    _, _, order = _paid_order_515(api)
    validate_error(api.post_payment(order["id"], {"amount_cents": 1, "method": "CARD"}, ASSOCIATE),
                   "ERR_ORDER_NOT_PAYABLE")
    after = get_order(order["id"])
    assert after["payment_status"] == "PAID_IN_FULL"
    assert after["amount_paid_cents"] == 515_000, "rejected payment must not post"
    assert after["balance_cents"] == 0


def test_pure_overpayment_rejected(api):
    """PRD §3.5: "The amount may not exceed the `balance_cents` — an overpayment is rejected
    with `ERR_OVERPAYMENT` (HTTP 422)."
    (On an UNPAID order the state gate passes, isolating the money rule.)

    Design: Corner/validations/pure_overpayment_rejected
    """
    customer = create_customer(full_name="Pam Over", email="pam@x.com")
    instrument = create_available_instrument(serial_number="SN-OV-1")
    order = create_order(customer["id"], [order_line(instrument["id"], 500_000)])

    res = api.post_payment(order["id"], {"amount_cents": 600_000, "method": "CARD"}, ASSOCIATE)
    validate_error(res, "ERR_OVERPAYMENT")
    after = get_order(order["id"])
    assert after["amount_paid_cents"] == 0
    assert after["payment_status"] == "UNPAID"


def test_order_creation_with_reserved_instrument_rejected(api):
    """PRD §3.4: "Every instrument named in the lines must be `AVAILABLE`; any line naming
    an instrument that is not is rejected with `ERR_INSTRUMENT_NOT_AVAILABLE`."
    PRD §3.4: "As the order is created, each line instrument is reserved: `AVAILABLE` →
    `RESERVED`."

    Design: Difficulty/cross_entity_state_dependency/order_creation_requires_instrument_available
    """
    customer = create_customer(full_name="Gail Gate", email="gail@x.com")
    instrument = create_available_instrument(
        serial_number="SN-G-9", category="GRAND", manufacturer="Steinway", model="B",
        year_built=2022, condition_grade="GOOD", list_price_cents=500_000,
        floor_price_cents=400_000)
    first = create_order(customer["id"], [order_line(instrument["id"], 500_000)])
    assert first["id"]

    res = api.create_sales_order(
        create_order_payload(customer["id"], [order_line(instrument["id"], 500_000)]),
        ASSOCIATE)
    validate_error(res, "ERR_INSTRUMENT_NOT_AVAILABLE")


def test_order_creation_rejection_preserves_reservation(api):
    """PRD §3.4: "Every instrument named in the lines must be `AVAILABLE`; any line naming
    an instrument that is not is rejected with `ERR_INSTRUMENT_NOT_AVAILABLE`."
    PRD §3.4: "As the order is created, each line instrument is reserved: `AVAILABLE` →
    `RESERVED`."

    Design: Difficulty/cross_entity_state_dependency/order_creation_requires_instrument_available
    """
    customer = create_customer(full_name="Gail Gate", email="gail@x.com")
    instrument = create_available_instrument(
        serial_number="SN-G-9", category="GRAND", manufacturer="Steinway", model="B",
        year_built=2022, condition_grade="GOOD", list_price_cents=500_000,
        floor_price_cents=400_000)
    create_order(customer["id"], [order_line(instrument["id"], 500_000)])

    validate_error(api.create_sales_order(
        create_order_payload(customer["id"], [order_line(instrument["id"], 500_000)]),
        ASSOCIATE), "ERR_INSTRUMENT_NOT_AVAILABLE")
    after = get_instrument(instrument["id"])
    assert after["status"] == "RESERVED", "the first order's reservation must survive"


def test_delivery_scheduling_on_unpaid_order_rejected(api):
    """PRD §3.6: "Scheduling requires the order's `fulfillment_status` to be
    `AWAITING_SCHEDULING` and its `payment_status` to be one of `DEPOSIT_PAID`,
    `PAID_IN_FULL`, or `FINANCED_ACTIVE`; otherwise the request is rejected with
    `ERR_DELIVERY_NOT_ACTIONABLE`."

    Design: Difficulty/cross_entity_state_dependency/delivery_scheduling_requires_payable_order_gate
    """
    customer = create_customer(full_name="Uma Unpaid", email="uma@x.com")
    instrument = create_available_instrument(
        serial_number="SN-U-1", category="UPRIGHT", manufacturer="Yamaha", model="U1",
        year_built=2023, list_price_cents=400_000, floor_price_cents=300_000)
    order = create_order(customer["id"], [order_line(instrument["id"], 400_000)])
    crew = create_delivery_crew(crew_name="Crew Epsilon", climate_certified=False)

    res = api.create_delivery_job(
        create_delivery_job_payload(order["id"], crew["id"],
                                    "2026-06-05T09:00:00Z", "2026-06-05T12:00:00Z"),
        COORDINATOR)
    validate_error(res, "ERR_DELIVERY_NOT_ACTIONABLE")


def test_delivery_scheduling_rejection_leaves_order_awaiting(api):
    """PRD §3.6: "Scheduling requires the order's `fulfillment_status` to be
    `AWAITING_SCHEDULING` and its `payment_status` to be one of `DEPOSIT_PAID`,
    `PAID_IN_FULL`, or `FINANCED_ACTIVE`; otherwise the request is rejected with
    `ERR_DELIVERY_NOT_ACTIONABLE`."
    PRD §3.6: "Delivery jobs may be listed filtered by `order_id` or `crew_id`."

    Design: Difficulty/cross_entity_state_dependency/delivery_scheduling_requires_payable_order_gate
    """
    customer = create_customer(full_name="Uma Unpaid", email="uma@x.com")
    instrument = create_available_instrument(
        serial_number="SN-U-1", category="UPRIGHT", manufacturer="Yamaha", model="U1",
        year_built=2023, list_price_cents=400_000, floor_price_cents=300_000)
    order = create_order(customer["id"], [order_line(instrument["id"], 400_000)])
    crew = create_delivery_crew(crew_name="Crew Epsilon", climate_certified=False)

    validate_error(api.create_delivery_job(
        create_delivery_job_payload(order["id"], crew["id"],
                                    "2026-06-05T09:00:00Z", "2026-06-05T12:00:00Z"),
        COORDINATOR), "ERR_DELIVERY_NOT_ACTIONABLE")
    after = get_order(order["id"])
    assert after["fulfillment_status"] == "AWAITING_SCHEDULING"
    jobs, meta = validate_paginated(
        api.list_delivery_jobs(COORDINATOR, params={"order_id": order["id"]}))
    assert meta["total_count"] == 0, "no delivery job may be persisted for the rejected request"


def test_order_with_offered_appraisal_rejected(api):
    """PRD §3.4: "A trade-in reference must point to an appraisal in `ACCEPTED` that belongs
    to the order's customer; anything else is rejected with `ERR_TRADE_IN_NOT_ACCEPTED`
    (HTTP 422)."

    Design: Corner/validations/order_with_offered_appraisal_rejected
    """
    customer = create_customer(full_name="Olive Offer", email="olive@x.com")
    appraisal = create_offered_appraisal(customer["id"], 0, 0.0)
    assert appraisal["status"] == "OFFERED"
    instrument = create_available_instrument(
        serial_number="SN-OF-1", category="GRAND", manufacturer="Steinway", model="M",
        year_built=2023, list_price_cents=500_000, floor_price_cents=400_000)

    res = api.create_sales_order(
        create_order_payload(customer["id"], [order_line(instrument["id"], 500_000)],
                             trade_in_appraisal_id=appraisal["id"]),
        ASSOCIATE)
    validate_error(res, "ERR_TRADE_IN_NOT_ACCEPTED")
    after = get_instrument(instrument["id"])
    assert after["status"] == "AVAILABLE", "rejected create must not reserve the instrument"


def test_order_with_non_awarded_bid_rejected(api):
    """PRD §3.4: "A bid reference must point to a package in `AWARDED` owned by that
    customer; otherwise the create is rejected with `ERR_BID_NOT_ACTIONABLE`."

    Design: Corner/validations/order_with_non_awarded_bid_rejected
    """
    customer = create_customer(full_name="Metro District", email="fac@metro.gov",
                               customer_type="INSTITUTIONAL", institution_type="GOVERNMENT",
                               state_contract_ceiling_cents=900_000)
    instrument = create_available_instrument(serial_number="SN-NB-1")
    bid = create_bid(customer["id"], [bid_line(instrument["id"], 500_000)],
                     officer_user_id="ibo-nb")
    submit_bid(bid["id"], officer_user_id="ibo-nb")

    res = api.create_sales_order(
        create_order_payload(customer["id"], [order_line(instrument["id"], 465_000)],
                             bid_package_id=bid["id"]),
        ASSOCIATE)
    validate_error(res, "ERR_BID_NOT_ACTIONABLE")
