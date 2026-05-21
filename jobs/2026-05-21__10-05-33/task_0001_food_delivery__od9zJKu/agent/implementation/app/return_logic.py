"""Return lifecycle: open, approve, reject, escalate, reopen."""
from __future__ import annotations

import datetime as _dt

from . import metrics
from .clock import clock, iso_now
from .entities import bump, init_unversioned, init_versioned
from .envelope import (
    err_duplicate_return,
    err_forbidden,
    err_invalid_state,
    err_refund_amount_invalid,
    err_return_window_expired,
    err_validation,
)
from .store import store


RETURN_REASONS = {"QUALITY_ISSUE", "WRONG_ITEM", "LATE", "OTHER"}
RETURN_WINDOW_SECONDS = 24 * 3600


def _parse_iso(s: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def open_return(order: dict, reason: str, requested_refund_cents) -> dict:
    # Duplicate return check (uniqueness, runs before state check so the more specific
    # error fires when the order's non-DELIVERED state is itself caused by a prior return).
    for r in store.returns.values():
        if r["order_id"] == order["id"] and r["status"] in (
            "REQUESTED",
            "APPROVED",
            "ESCALATED",
        ):
            raise err_duplicate_return()
    if order["status"] != "DELIVERED":
        raise err_invalid_state("Returns are only eligible for DELIVERED orders")
    # 24-hour window
    actual = _parse_iso(order["actual_delivery_time"])
    now = clock.now()
    if (now - actual).total_seconds() > RETURN_WINDOW_SECONDS:
        raise err_return_window_expired()
    # Refund range
    if not isinstance(requested_refund_cents, int) or isinstance(requested_refund_cents, bool):
        raise err_refund_amount_invalid("requested_refund_cents must be an integer")
    if requested_refund_cents < 1 or requested_refund_cents > order["subtotal_cents"]:
        raise err_refund_amount_invalid()
    # Reason validation
    if reason not in RETURN_REASONS:
        raise err_validation("reason must be one of QUALITY_ISSUE/WRONG_ITEM/LATE/OTHER")
    ret = init_versioned("Return")
    ret.update(
        {
            "order_id": order["id"],
            "reason": reason,
            "requested_refund_cents": requested_refund_cents,
            "approved_refund_cents": None,
            "status": "REQUESTED",
            "reviewer_cs_user_id": None,
        }
    )
    store.returns[ret["id"]] = ret
    # Order transitions to REFUND_REQUESTED
    order["status"] = "REFUND_REQUESTED"
    bump(order)
    return ret


def approve_return(ret: dict, approved_refund_cents, reviewer_id: str) -> None:
    if ret["status"] not in ("REQUESTED", "ESCALATED"):
        raise err_invalid_state(f"Return in state {ret['status']} cannot be approved")
    order = store.orders[ret["order_id"]]
    if not isinstance(approved_refund_cents, int) or isinstance(approved_refund_cents, bool):
        raise err_refund_amount_invalid("approved_refund_cents must be an integer")
    if approved_refund_cents < 1:
        raise err_refund_amount_invalid()
    if approved_refund_cents > order["subtotal_cents"]:
        raise err_refund_amount_invalid()
    if approved_refund_cents > ret["requested_refund_cents"]:
        raise err_refund_amount_invalid()

    ret["status"] = "APPROVED"
    ret["approved_refund_cents"] = approved_refund_cents
    ret["reviewer_cs_user_id"] = reviewer_id
    bump(ret)

    # Order: REFUND_REQUESTED -> REFUNDED; payment_status updated.
    order["status"] = "REFUNDED"
    if approved_refund_cents == order["subtotal_cents"]:
        order["payment_status"] = "FULLY_REFUNDED"
    else:
        order["payment_status"] = "PARTIALLY_REFUNDED"
    bump(order)

    # Customer credit_balance += approved_refund_cents
    customer = store.customers[order["customer_id"]]
    customer["credit_balance_cents"] = customer.get("credit_balance_cents", 0) + approved_refund_cents
    bump(customer)

    # Restaurant pending_settlement -= approved_refund_cents
    restaurant = store.restaurants[order["restaurant_id"]]
    restaurant["pending_settlement_cents"] = (
        restaurant.get("pending_settlement_cents", 0) - approved_refund_cents
    )
    bump(restaurant)

    # Abusive return fine when trust_score < 0.5 and reason == QUALITY_ISSUE
    if customer["trust_score"] < 0.5 and ret["reason"] == "QUALITY_ISSUE":
        fine = init_unversioned("Fine")
        fine.update(
            {
                "subject_type": "CUSTOMER",
                "subject_id": customer["id"],
                "reason": "ABUSIVE_RETURN",
                "amount_cents": approved_refund_cents,
                "settlement_status": "PENDING",
            }
        )
        store.fines[fine["id"]] = fine
        # The fine debits the customer's credit balance? PRD says "Customer's credit balance is restored" on waive.
        # So accepting a fine debits the credit balance.
        customer["credit_balance_cents"] = max(
            0, customer.get("credit_balance_cents", 0) - approved_refund_cents
        )
        bump(customer)


def reject_return(ret: dict, reviewer_id: str) -> None:
    if ret["status"] not in ("REQUESTED", "ESCALATED"):
        raise err_invalid_state(f"Return in state {ret['status']} cannot be rejected")
    ret["status"] = "REJECTED"
    ret["reviewer_cs_user_id"] = reviewer_id
    bump(ret)
    order = store.orders[ret["order_id"]]
    # Revert to DELIVERED
    order["status"] = "DELIVERED"
    bump(order)


def escalate_return(ret: dict, reviewer_id: str) -> dict:
    """Escalate REQUESTED -> ESCALATED and open a WorkOrder linked to it."""
    if ret["status"] != "REQUESTED":
        raise err_invalid_state(f"Return in state {ret['status']} cannot be escalated")
    ret["status"] = "ESCALATED"
    ret["reviewer_cs_user_id"] = reviewer_id
    bump(ret)
    # Open WorkOrder
    wo = init_versioned("WorkOrder")
    wo.update(
        {
            "opened_by_role": "CUSTOMER_SERVICE",
            "opened_by_id": reviewer_id,
            "category": "OTHER",
            "related_order_id": ret["order_id"],
            "related_return_id": ret["id"],
            "status": "OPEN",
            "resolution_notes": None,
            "assigned_cs_user_id": None,
        }
    )
    store.work_orders[wo["id"]] = wo
    return wo


def reopen_return(ret: dict) -> None:
    """ESCALATED -> REQUESTED; close any linked WorkOrder."""
    if ret["status"] != "ESCALATED":
        raise err_invalid_state(f"Return in state {ret['status']} cannot be reopened")
    ret["status"] = "REQUESTED"
    bump(ret)
    # Find any open work order linked to this return; close it.
    for wo in store.work_orders.values():
        if wo.get("related_return_id") == ret["id"] and wo["status"] not in ("CLOSED",):
            # Auto-close (terminal). PRD: "that ticket is closed automatically when the return is reopened"
            wo["status"] = "CLOSED"
            bump(wo)
