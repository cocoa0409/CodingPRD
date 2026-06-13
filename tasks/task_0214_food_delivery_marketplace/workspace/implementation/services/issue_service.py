"""OrderIssue adjudication (PRD §3.12)."""
import errors
from common import touch
from db import store
from services import calculations as calc


def approve_issue(issue, order):
    if issue["status"] != "OPEN":
        raise errors.err(errors.ERR_ISSUE_NOT_OPEN)
    if order["fulfillment_status"] != "DELIVERED":
        raise errors.err(errors.ERR_ORDER_NOT_DELIVERED)
    line = store.line_items[issue["line_item_id"]]
    if issue["missing_quantity"] > line["fulfilled_quantity"]:
        raise errors.err(errors.ERR_MISSING_QTY_EXCEEDS_FULFILLED)

    refund = calc.missing_item_refund(order, line, issue["missing_quantity"])
    issue["refund_amount_cents"] = refund
    issue["status"] = "APPROVED"
    touch(issue)

    # Decrement fulfilled quantity; line -> SHORTED if it reaches 0.
    line["fulfilled_quantity"] -= issue["missing_quantity"]
    if line["fulfilled_quantity"] <= 0:
        line["status"] = "SHORTED"
    touch(line)

    order["refunded_cents"] += refund

    if issue["refund_destination"] == "WALLET":
        customer = store.customers[order["customer_id"]]
        customer["wallet_credit_cents"] += refund
        touch(customer)

    # Full-refund billing transition (valid only from SETTLED).
    if order["refunded_cents"] >= order["order_subtotal_cents"]:
        if order["billing_status"] != "SETTLED":
            raise errors.err(errors.ERR_INVALID_BILLING_STATE)
        order["billing_status"] = "REFUNDED"

    touch(order)


def reject_issue(issue):
    if issue["status"] != "OPEN":
        raise errors.err(errors.ERR_ISSUE_NOT_OPEN)
    issue["status"] = "REJECTED"
    # refund_amount_cents stays 0; no ledger movement.
    touch(issue)
