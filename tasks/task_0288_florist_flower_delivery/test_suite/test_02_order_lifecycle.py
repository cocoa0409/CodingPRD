"""Order lifecycle: parallel state dimensions, transitions, dispatch capture.

Translates queue-A Difficulty non_linear_state_machine (order parallel dims),
and queue-B Corner state_machines / entities / consistency_model / cross-cutting
instances for the Order.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    make_customer_headers, make_florist_headers,
    set_clock, create_zone, create_arrangement, create_customer, create_florist,
    create_draft_order, quote_order, mark_authorized, book_order,
    get_order_wire_fulfillment, accept_wire_fulfillment,
    setup_quoted_order, setup_authorized_order, setup_delivered_order,
    setup_accepted_order, TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_book_sets_parallel_payment_and_fulfillment_dimensions(api):
    """PRD §3.4: "Once an order is `QUOTED`, the customer authorizes payment, which
    advances the `payment_status` dimension from `UNPAID` to `AUTHORIZED`
    independently of the fulfillment dimension."
    PRD §3.4: "Booking advances `fulfillment_status` from `QUOTED` to `BOOKED`".

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    ctx, order = setup_authorized_order(
        "2026-05-01T08:00:00Z",
        zone_overrides={"zone_code": "Z5", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A5", "display_name": "Bouquet5", "base_price_cents": 5000},
        order_overrides={"delivery_date": "2026-05-05", "window_start_minute": 540,
                         "window_end_minute": 720})
    booked = book_order(order, ctx["customer"], order["version"])
    assert booked["fulfillment_status"] == "BOOKED"
    assert booked["payment_status"] == "AUTHORIZED"


def test_authorized_payment_does_not_advance_fulfillment(api):
    """PRD §3.4: "Authorization is only defined when `payment_status` is `UNPAID`
    and the order's `fulfillment_status` is `QUOTED`; it records the authorized
    amount as the order's `estimated_total_cents`".

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    ctx, order = setup_authorized_order(
        "2026-05-02T08:00:00Z",
        zone_overrides={"zone_code": "Z5b", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "A5b", "display_name": "Bouquet5b", "base_price_cents": 5000},
        order_overrides={"delivery_date": "2026-05-06", "window_start_minute": 540,
                         "window_end_minute": 720})
    # After authorize: payment advanced but fulfillment remained QUOTED.
    assert order["payment_status"] == "AUTHORIZED"
    assert order["fulfillment_status"] == "QUOTED"


def test_create_order_stamps_system_fields(api):
    """PRD §3.2: "A freshly drafted order begins with `fulfillment_status` of
    `DRAFT` and `payment_status` of `UNPAID`."
    PRD §2.4: "a system-managed integer that begins at creation and increments by
    one with every mutation of the resource."

    Design: Corner/entities/order_system_fields_generated_input_ignored
    """
    set_clock("2026-11-01T08:00:00Z")
    zone = create_zone(zone_code="ZC5", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="CC5", display_name="CC5", base_price_cents=5000)
    cust = create_customer(email="sf@x.com", full_name="SF C")
    order = create_draft_order(cust, arr, zone, delivery_date="2026-11-01",
                               window_start_minute=540, window_end_minute=720)
    assert order["fulfillment_status"] == "DRAFT"
    assert order["payment_status"] == "UNPAID"
    assert order["version"] == 1
    assert order["estimated_total_cents"] == 0


def test_quote_already_quoted_returns_invalid_state(api):
    """PRD §3.2: "Quoting is only defined from `DRAFT`; attempting it from any other
    state yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/quote_from_already_quoted_returns_invalid_state
    """
    ctx, order = setup_quoted_order(
        "2026-11-01T08:00:00Z",
        zone_overrides={"zone_code": "ZS1", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "CS1", "display_name": "CS1", "base_price_cents": 5000},
        order_overrides={"delivery_date": "2026-11-05", "window_start_minute": 540,
                         "window_end_minute": 720},
        with_florist=False)
    res = api.quote_order(order["id"], make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_delivered_order_returns_invalid_state(api):
    """PRD §3.6: "cancellation from any other state — already in transit,
    delivered, or cancelled — is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_delivered_order_returns_invalid_state
    """
    ctx, order, _wf = setup_delivered_order(
        "2026-11-08T08:00:00Z",
        zone_overrides={"zone_code": "ZS2", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "CS2", "display_name": "CS2", "base_price_cents": 5000},
        order_overrides={"delivery_date": "2026-11-12", "window_start_minute": 540,
                         "window_end_minute": 720})
    res = api.cancel_order(order["id"], make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_order(order["id"], DISPATCHER), 200)
    assert after["fulfillment_status"] == "DELIVERED"


def test_book_without_authorized_payment_returns_precondition(api):
    """PRD §3.4: "it carries the cross-dimension precondition that the order's
    `payment_status` is already `AUTHORIZED`; an attempt to book an order whose
    payment is not yet authorized is rejected with `ERR_PRECONDITION_NOT_MET`."

    Design: Corner/state_machines/book_without_authorized_payment_returns_precondition
    """
    ctx, order = setup_quoted_order(
        "2026-11-15T08:00:00Z",
        zone_overrides={"zone_code": "ZS3", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "CS3", "display_name": "CS3", "base_price_cents": 5000},
        order_overrides={"delivery_date": "2026-11-20", "window_start_minute": 540,
                         "window_end_minute": 720})
    res = api.book_order(order["id"], {"expected_order_version": order["version"]},
                         make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_PRECONDITION_NOT_MET", expected_status=409)
    after = validate_success(api.get_order(order["id"], DISPATCHER), 200)
    assert after["fulfillment_status"] == "QUOTED"


def test_dispatch_captures_final_amount_in_same_request(api):
    """PRD §3.5: "Dispatch runs the **final total** calculation and, as a coupled
    side effect on the payment dimension, captures payment by advancing
    `payment_status` from `AUTHORIZED` to `CAPTURED` at the just-computed final
    amount."

    Design: Corner/consistency_model/dispatch_captures_final_amount_in_same_request
    """
    ctx, order, _wf = setup_accepted_order(
        "2027-09-01T08:00:00Z",
        zone_overrides={"zone_code": "ZM1", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "CM1", "display_name": "CM1", "base_price_cents": 5000},
        florist_overrides={"shop_name": "ShopM1", "wire_surcharge_cents": 0},
        order_overrides={"delivery_date": "2027-09-05", "window_start_minute": 540,
                         "window_end_minute": 720})
    dispatched = validate_success(
        api.dispatch_order(order["id"], make_florist_headers(ctx["florist"]["id"])), 200)
    assert dispatched["final_total_cents"] == 5800, dispatched["final_total_cents"]
    assert dispatched["payment_status"] == "CAPTURED"
    assert dispatched["fulfillment_status"] == "IN_TRANSIT"


def test_order_version_increments_on_every_mutation(api):
    """PRD §2.6: "Whenever an operation writes to a resource, that resource's
    `updated_at` is refreshed and its `version` is incremented by one."
    PRD §3.4: "it too increments the order's `version`." (mark_authorized helper)

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_mutation
    """
    set_clock("2027-08-01T08:00:00Z")
    zone = create_zone(zone_code="ZL1", base_delivery_fee_cents=800,
                       same_day_cutoff_hour_utc=14, window_capacity_per_slot=5)
    arr = create_arrangement(sku="CL1", display_name="CL1", base_price_cents=5000)
    cust = create_customer(email="vi@x.com", full_name="VI C")
    order = create_draft_order(cust, arr, zone, delivery_date="2027-08-05",
                               window_start_minute=540, window_end_minute=720)
    assert order["version"] == 1, "version is 1 at creation"
    quoted = quote_order(order, cust)
    assert quoted["version"] == 2, "version is 2 after quote"
    authed = mark_authorized(order["id"])
    assert authed["version"] == 3, "version is 3 after authorize"


def test_confirm_delivery_increments_lifetime_count(api):
    """PRD §3.5: "On delivery the customer's `lifetime_delivered_count` is
    incremented by one and the loyalty recomputation runs, after which the order's
    `version` increments."

    Design: Corner/endpoints/confirm_delivery_increments_lifetime_count
    """
    ctx, order, _wf = setup_accepted_order(
        "2027-05-01T08:00:00Z",
        zone_overrides={"zone_code": "ZE1", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "CE1", "display_name": "CE1", "base_price_cents": 5000},
        order_overrides={"delivery_date": "2027-05-05", "window_start_minute": 540,
                         "window_end_minute": 720})
    validate_success(api.dispatch_order(order["id"], make_florist_headers(ctx["florist"]["id"])), 200)
    delivered = validate_success(
        api.confirm_delivery(order["id"], make_florist_headers(ctx["florist"]["id"])), 200)
    assert delivered["fulfillment_status"] == "DELIVERED"
    cust = validate_success(api.get_customer(ctx["customer"]["id"], DISPATCHER), 200)
    assert cust["lifetime_delivered_count"] == 1
