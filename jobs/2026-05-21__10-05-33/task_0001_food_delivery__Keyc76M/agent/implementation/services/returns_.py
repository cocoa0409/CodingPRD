"""Return / refund service.

Handles the full §3.9 flow: open, approve, reject, escalate, reopen.
Approval cascades into customer credit, restaurant settlement, payment
status, and an ABUSIVE_RETURN fine when the customer's trust_score < 0.5.
"""

from datetime import timedelta

import envelope
import projection
import state
import validators
from services import customers as csvc
from services import fines as fines_svc
from services import orders as osvc
from services import restaurants as rsvc
from services import work_orders as wo_svc


_LEGAL_REASONS = {"QUALITY_ISSUE", "WRONG_ITEM", "LATE", "OTHER"}


def _bump(rec):
    rec["updated_at"] = state.now()
    rec["version"] = rec["version"] + 1


def open_return(order_id, user_id, payload):
    with state.lock():
        order = state.STORE.orders.get(order_id)
        if order is None:
            return envelope.not_found("Order not found.")
        if user_id != order["customer_id"]:
            return envelope.forbidden()
        if "reason" not in payload or payload["reason"] not in _LEGAL_REASONS:
            return envelope.validation(
                "reason must be one of QUALITY_ISSUE, WRONG_ITEM, LATE, OTHER."
            )
        if "requested_refund_cents" not in payload or \
                not validators.is_int(payload["requested_refund_cents"]):
            return envelope.validation(
                "requested_refund_cents must be an integer."
            )

        # Duplicate-return check runs before status because opening a return
        # cascades the order to REFUND_REQUESTED — without checking dupes
        # first, the second call would mis-report ERR_INVALID_STATE.
        for r in state.STORE.returns.values():
            if r["order_id"] != order_id:
                continue
            if r["status"] in ("REQUESTED", "APPROVED", "ESCALATED"):
                return envelope.error(
                    409, "ERR_DUPLICATE_RETURN",
                    "Another return is already open for this order.",
                )

        if order["status"] != "DELIVERED":
            return envelope.invalid_state(
                "Order must be DELIVERED to open a return."
            )
        if order["actual_delivery_time"] is None:
            return envelope.invalid_state("Order has no delivery time.")
        if state.now() - order["actual_delivery_time"] > timedelta(hours=24):
            return envelope.error(
                422, "ERR_RETURN_WINDOW_EXPIRED",
                "Return window has expired (24h since delivery).",
            )

        amount = int(payload["requested_refund_cents"])
        if amount < 1 or amount > order["subtotal_cents"]:
            return envelope.error(
                422, "ERR_REFUND_AMOUNT_INVALID",
                "requested_refund_cents must be in [1, subtotal_cents].",
            )

        now = state.now()
        rid = state.gen_id()
        rec = {
            "id": rid,
            "order_id": order_id,
            "reason": payload["reason"],
            "requested_refund_cents": amount,
            "approved_refund_cents": None,
            "reviewer_cs_user_id": None,
            "status": "REQUESTED",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        state.STORE.returns[rid] = rec
        order["status"] = "REFUND_REQUESTED"
        osvc.bump(order)
        return envelope.created(projection.render(rec))


def approve(return_id, user_id, payload):
    with state.lock():
        ret = state.STORE.returns.get(return_id)
        if ret is None:
            return envelope.not_found("Return not found.")
        if ret["status"] not in ("REQUESTED", "ESCALATED"):
            return envelope.invalid_state(
                "Return must be REQUESTED or ESCALATED to approve."
            )
        if "approved_refund_cents" not in payload or \
                not validators.is_int(payload["approved_refund_cents"]):
            return envelope.validation(
                "approved_refund_cents must be an integer."
            )
        amount = int(payload["approved_refund_cents"])
        order = state.STORE.orders.get(ret["order_id"])
        if order is None:
            return envelope.not_found("Underlying order not found.")
        if amount < 1 or amount > order["subtotal_cents"] \
                or amount > ret["requested_refund_cents"]:
            return envelope.error(
                422, "ERR_REFUND_AMOUNT_INVALID",
                "approved_refund_cents out of range.",
            )

        # If escalated, close the linked work order.
        if ret["status"] == "ESCALATED":
            _close_linked_workorder(ret["id"])

        ret["status"] = "APPROVED"
        ret["approved_refund_cents"] = amount
        ret["reviewer_cs_user_id"] = user_id
        _bump(ret)

        # Order cascade
        order["status"] = "REFUNDED"
        if amount == order["subtotal_cents"]:
            order["payment_status"] = "FULLY_REFUNDED"
        else:
            order["payment_status"] = "PARTIALLY_REFUNDED"
        osvc.bump(order)

        # Customer credit
        customer = state.STORE.customers.get(order["customer_id"])
        if customer is not None:
            customer["credit_balance_cents"] += amount
            csvc.bump(customer)

        # Restaurant settlement
        restaurant = state.STORE.restaurants.get(order["restaurant_id"])
        if restaurant is not None:
            restaurant["pending_settlement_cents"] -= amount
            rsvc.bump(restaurant)

        # ABUSIVE_RETURN fine when customer trust < 0.5 and reason QUALITY_ISSUE
        if customer is not None \
                and customer["trust_score"] < 0.5 \
                and ret["reason"] == "QUALITY_ISSUE":
            fines_svc.issue_customer_fine(
                customer, "ABUSIVE_RETURN", amount,
                related_order_id=order["id"],
            )

        return envelope.success(projection.render(ret))


def reject(return_id, user_id):
    with state.lock():
        ret = state.STORE.returns.get(return_id)
        if ret is None:
            return envelope.not_found("Return not found.")
        if ret["status"] not in ("REQUESTED", "ESCALATED"):
            return envelope.invalid_state(
                "Return must be REQUESTED or ESCALATED to reject."
            )
        if ret["status"] == "ESCALATED":
            _close_linked_workorder(ret["id"])
        ret["status"] = "REJECTED"
        ret["reviewer_cs_user_id"] = user_id
        _bump(ret)
        order = state.STORE.orders.get(ret["order_id"])
        if order is not None and order["status"] == "REFUND_REQUESTED":
            order["status"] = "DELIVERED"
            osvc.bump(order)
        return envelope.success(projection.render(ret))


def escalate(return_id, user_id):
    with state.lock():
        ret = state.STORE.returns.get(return_id)
        if ret is None:
            return envelope.not_found("Return not found.")
        if ret["status"] != "REQUESTED":
            return envelope.invalid_state(
                "Return must be REQUESTED to escalate."
            )
        ret["status"] = "ESCALATED"
        _bump(ret)
        wo_svc.new_work_order(
            opened_by_role="CUSTOMER_SERVICE",
            opened_by_id=user_id,
            category="OTHER",
            related_return_id=ret["id"],
            related_order_id=ret["order_id"],
            assigned_cs_user_id=user_id,
            status="UNDER_REVIEW",
        )
        return envelope.success(projection.render(ret))


def reopen(return_id, user_id):
    with state.lock():
        ret = state.STORE.returns.get(return_id)
        if ret is None:
            return envelope.not_found("Return not found.")
        if ret["status"] != "ESCALATED":
            return envelope.invalid_state(
                "Return must be ESCALATED to reopen."
            )
        ret["status"] = "REQUESTED"
        _bump(ret)
        _close_linked_workorder(ret["id"])
        return envelope.success(projection.render(ret))


def _close_linked_workorder(return_id):
    """Close any open work-order linked to this return (escalation companion)."""
    for w in state.STORE.work_orders.values():
        if w.get("related_return_id") == return_id \
                and w["status"] not in ("RESOLVED", "CLOSED"):
            w["status"] = "CLOSED"
            wo_svc.bump(w)
