"""Validation corner tests: frame-not-bike, mandatory-recall block, target not
payable, duplicate recall ack, frame-not-serialized coverage, deliver unpaid
(PRD §3.5, §3.6, §3.9, §3.10, §3.11, §2.9).

Queue B — corner section: validations (non-stub instances).
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_customer, create_sku, create_order, add_order_line, get_sku,
    create_delivered_purchase, create_under_review_claim, publish_recall,
    create_build_job_payload, create_recall_notice_payload,
    create_recall_ack_payload, reserve_payload, create_payment_payload,
    approve_warranty_payload,
    make_customer_headers, TEST_USERS,
)

MGR = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["sales_associate_headers"]
ADV = TEST_USERS["service_advisor_headers"]


def test_frame_sku_not_bike_rejected():
    """PRD §3.9: "the frame's `Sku` must be of `category` `BIKE`, and a build
    whose frame is not a bike is rejected at creation with `ERR_FRAME_NOT_BIKE`."

    A BuildJob whose frame_sku_id points at a PART returns ERR_FRAME_NOT_BIKE.

    Design: Corner/validations/frame_sku_not_bike_rejected
    """
    cust = create_customer()
    sku = create_sku(name="Not A Frame", category="PART", list_price_cents=2000, on_hand=5)
    res = api_client.create_build_job(
        create_build_job_payload(cust["id"], sku["id"], 1), ADV)
    validate_error(res, "ERR_FRAME_NOT_BIKE")


def test_mandatory_recall_blocks_reserve():
    """PRD §2.9: "When a stock-keeping unit is under an active `MANDATORY`
    recall, the shop must not promise or hand over more of it: reserving stock
    for a sales order, receiving a special order into stock, and opening a
    layaway plan are all blocked with `ERR_RECALL_BLOCK` while such a recall
    stands."

    Reserving a Sku that has a MANDATORY recall returns ERR_RECALL_BLOCK.

    Design: Corner/validations/mandatory_recall_blocks_reserve
    """
    cust = create_customer()
    sku = create_sku(name="Dangerous Fork", category="PART", list_price_cents=9000, on_hand=5)
    publish_recall(sku["id"], "MANDATORY")
    order = create_order(cust["id"])
    add_order_line(order["id"], sku["id"], 1)
    v = get_sku(sku["id"])["version"]
    res = api_client.reserve_sales_order(order["id"], reserve_payload(v), SA)
    validate_error(res, "ERR_RECALL_BLOCK")


def test_payment_against_delivered_order_not_payable():
    """PRD §3.6: "A payment may not be captured against a target whose lifecycle
    no longer accepts payments: a sales order whose fulfillment is `CANCELLED` or
    `DELIVERED` ... Such an attempt is rejected with `ERR_TARGET_NOT_PAYABLE`."

    A payment against an already-DELIVERED SALES_ORDER returns
    ERR_TARGET_NOT_PAYABLE.

    Design: Corner/validations/payment_against_delivered_order_not_payable
    """
    cust = create_customer()
    sku = create_sku(name="Finished Good", category="ACCESSORY", list_price_cents=5000, on_hand=3)
    cust2, order, line = create_delivered_purchase(sku["id"], qty=1, customer_id=cust["id"])
    res = api_client.create_payment(
        create_payment_payload("SALES_ORDER", order["id"], 100), SA)
    validate_error(res, "ERR_TARGET_NOT_PAYABLE")


def test_duplicate_recall_ack_rejected():
    """PRD §3.11: "A customer may acknowledge a given notice at most once; a
    duplicate acknowledgement is rejected with `ERR_ALREADY_ACKNOWLEDGED`."

    A second acknowledgement of the same RecallNotice by the same customer
    returns ERR_ALREADY_ACKNOWLEDGED.

    Design: Corner/validations/duplicate_recall_ack_rejected
    """
    cust = create_customer()
    sku = create_sku(name="Ack Sku", category="BIKE", list_price_cents=30000, on_hand=2)
    rn = validate_success(api_client.create_recall_notice(
        create_recall_notice_payload(sku["id"], "ADVISORY"), MGR), 201)
    cust_headers = make_customer_headers(cust["id"])
    validate_success(api_client.create_recall_ack(
        create_recall_ack_payload(rn["id"], cust["id"]), cust_headers), 201)
    res = api_client.create_recall_ack(
        create_recall_ack_payload(rn["id"], cust["id"]), cust_headers)
    validate_error(res, "ERR_ALREADY_ACKNOWLEDGED")


def test_warranty_frame_not_serialized_not_covered():
    """PRD §3.10: "when `defect_part` is `FRAME`, the source `Sku` must have
    `warranty_class` of `FRAME_AND_COMPONENT` and `is_serialized` true ... A
    coverage failure is rejected with `ERR_WARRANTY_NOT_COVERED`."

    Approving a FRAME claim on a FRAME_AND_COMPONENT but NOT-serialized Sku (with
    a valid delivered purchase) returns ERR_WARRANTY_NOT_COVERED.

    Design: Corner/validations/warranty_frame_not_serialized_not_covered
    """
    cust = create_customer()
    sku = create_sku(name="Unserialized Frame", category="BIKE", list_price_cents=70000,
                     on_hand=2, warranty_class="FRAME_AND_COMPONENT", is_serialized=False)
    cust2, claim, line = create_under_review_claim(sku["id"], "FRAME", customer_id=cust["id"])
    res = api_client.approve_warranty_claim(claim["id"], approve_warranty_payload("REPAIR"), ADV)
    validate_error(res, "ERR_WARRANTY_NOT_COVERED")


def test_deliver_unpaid_reserved_not_fully_paid():
    """PRD §3.5: "Delivery is permitted only from `RESERVED` and only when the
    order's `payment_status` is `PAID`; a delivery attempted on an order that is
    not fully paid is rejected with `ERR_NOT_FULLY_PAID`."

    Delivering a RESERVED but UNPAID order returns ERR_NOT_FULLY_PAID (the
    single-failure case).

    Design: Corner/validations/deliver_unpaid_reserved_not_fully_paid
    """
    from test_helpers import create_reserved_order
    cust = create_customer()
    sku = create_sku(name="Unpaid Part", category="PART", list_price_cents=4000, on_hand=5)
    cust2, order, line = create_reserved_order(sku["id"], qty=1, customer_id=cust["id"])
    assert order["payment_status"] == "UNPAID"
    res = api_client.deliver_sales_order(order["id"], SA)
    validate_error(res, "ERR_NOT_FULLY_PAID")
