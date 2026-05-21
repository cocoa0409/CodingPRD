from datetime import datetime, timedelta, timezone
from flask import Blueprint

from ..auth import require_role
from ..envelope import success, created
from ..errors import err
from ..repository import base_versioned, touch, check_version, body_or_empty, now_iso
from ..store import store
from ..domain.fines import create_fine

bp = Blueprint("returns", __name__)

_VALID_REASONS = {"QUALITY_ISSUE", "WRONG_ITEM", "LATE", "OTHER"}


def _view(r):
    return {k: r.get(k) for k in (
        "id", "order_id", "reason",
        "requested_refund_cents", "approved_refund_cents",
        "status", "reviewer_cs_user_id",
        "created_at", "updated_at", "version",
    )}


def _parse_iso(s):
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@bp.post("/api/orders/<oid>/returns")
def open_return(oid):
    uid, role = require_role("Customer")
    o = store.orders.get(oid)
    if o is None:
        raise err("ERR_NOT_FOUND", "order not found")
    if o["customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "not your order")
    # Duplicate return check — must precede state check per PRD
    for existing in store.returns.values():
        if existing["order_id"] == oid and existing["status"] in ("REQUESTED", "APPROVED", "ESCALATED"):
            raise err("ERR_DUPLICATE_RETURN", "active return exists")
    if o["status"] != "DELIVERED":
        raise err("ERR_INVALID_STATE", "order not in DELIVERED")
    # 24-hour return window
    from ..app import logical_clock
    actual = _parse_iso(o["actual_delivery_time"])
    if (logical_clock.now() - actual) > timedelta(hours=24):
        raise err("ERR_RETURN_WINDOW_EXPIRED", "return window expired")
    body = body_or_empty()
    reason = body.get("reason")
    if reason not in _VALID_REASONS:
        raise err("ERR_VALIDATION", "invalid reason")
    requested = body.get("requested_refund_cents")
    if not isinstance(requested, int) or isinstance(requested, bool):
        raise err("ERR_REFUND_AMOUNT_INVALID", "requested_refund_cents must be integer")
    if requested < 1 or requested > o["subtotal_cents"]:
        raise err("ERR_REFUND_AMOUNT_INVALID", "requested_refund_cents out of range")
    ret = base_versioned()
    ret.update({
        "order_id": oid,
        "reason": reason,
        "requested_refund_cents": requested,
        "approved_refund_cents": None,
        "status": "REQUESTED",
        "reviewer_cs_user_id": None,
    })
    store.returns[ret["id"]] = ret
    o["status"] = "REFUND_REQUESTED"
    touch(o)
    return created(_view(ret))


@bp.get("/api/returns/<rid>")
def get_return(rid):
    uid, role = require_role("PlatformAdmin", "Customer", "Restaurant", "CustomerService")
    ret = store.returns.get(rid)
    if ret is None:
        raise err("ERR_NOT_FOUND", "return not found")
    order = store.orders.get(ret["order_id"])
    if role == "Customer" and (order is None or order["customer_id"] != uid):
        raise err("ERR_FORBIDDEN", "not your return")
    if role == "Restaurant" and (order is None or order["restaurant_id"] != uid):
        raise err("ERR_FORBIDDEN", "not your return")
    return success(_view(ret))


@bp.post("/api/returns/<rid>/approve")
def approve_return(rid):
    uid, role = require_role("CustomerService")
    ret = store.returns.get(rid)
    if ret is None:
        raise err("ERR_NOT_FOUND", "return not found")
    if ret["status"] not in ("REQUESTED", "ESCALATED"):
        raise err("ERR_INVALID_STATE", "return not in REQUESTED or ESCALATED")
    body = body_or_empty()
    approved = body.get("approved_refund_cents")
    if not isinstance(approved, int) or isinstance(approved, bool):
        raise err("ERR_REFUND_AMOUNT_INVALID", "approved_refund_cents must be integer")
    order = store.orders[ret["order_id"]]
    if approved < 1 or approved > order["subtotal_cents"] or approved > ret["requested_refund_cents"]:
        raise err("ERR_REFUND_AMOUNT_INVALID", "approved_refund_cents out of range")
    check_version(ret, body)
    ret["status"] = "APPROVED"
    ret["approved_refund_cents"] = approved
    ret["reviewer_cs_user_id"] = uid
    touch(ret)
    # Cascade: order goes REFUNDED
    order["status"] = "REFUNDED"
    order["payment_status"] = "FULLY_REFUNDED" if approved == order["subtotal_cents"] else "PARTIALLY_REFUNDED"
    touch(order)
    # Credit customer
    customer = store.customers[order["customer_id"]]
    customer["credit_balance_cents"] = customer.get("credit_balance_cents", 0) + approved
    touch(customer)
    # Decrement restaurant pending settlement
    restaurant = store.restaurants[order["restaurant_id"]]
    restaurant["pending_settlement_cents"] = restaurant.get("pending_settlement_cents", 0) - approved
    touch(restaurant)
    # Abusive return fine for customers with trust_score < 0.5 + QUALITY_ISSUE
    if customer.get("trust_score", 1.0) < 0.5 and ret["reason"] == "QUALITY_ISSUE":
        # Apply abusive-return fine — this debits the customer's credit balance
        create_fine(
            subject_type="CUSTOMER",
            subject_id=customer["id"],
            reason="ABUSIVE_RETURN",
            amount_cents=approved,
            related_order_id=order["id"],
            related_return_id=ret["id"],
        )
        # Since create_fine doesn't touch, but we already touched customer above,
        # we need to touch customer again? No - we've folded all mutations to customer
        # into one touch already (credit_balance modified twice but version bumped once).
    return success(_view(ret))


@bp.post("/api/returns/<rid>/reject")
def reject_return(rid):
    uid, role = require_role("CustomerService")
    ret = store.returns.get(rid)
    if ret is None:
        raise err("ERR_NOT_FOUND", "return not found")
    if ret["status"] not in ("REQUESTED", "ESCALATED"):
        raise err("ERR_INVALID_STATE", "return not in REQUESTED or ESCALATED")
    body = body_or_empty()
    check_version(ret, body)
    ret["status"] = "REJECTED"
    ret["reviewer_cs_user_id"] = uid
    touch(ret)
    order = store.orders[ret["order_id"]]
    if order["status"] == "REFUND_REQUESTED":
        order["status"] = "DELIVERED"
        touch(order)
    return success(_view(ret))


@bp.post("/api/returns/<rid>/escalate")
def escalate_return(rid):
    uid, role = require_role("CustomerService")
    ret = store.returns.get(rid)
    if ret is None:
        raise err("ERR_NOT_FOUND", "return not found")
    if ret["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "return not in REQUESTED")
    body = body_or_empty()
    check_version(ret, body)
    ret["status"] = "ESCALATED"
    touch(ret)
    # Open WorkOrder linked to the return
    from ..domain.work_orders import open_workorder_for_return
    open_workorder_for_return(ret, opened_by_id=uid)
    return success(_view(ret))


@bp.post("/api/returns/<rid>/reopen")
def reopen_return(rid):
    uid, role = require_role("CustomerService")
    ret = store.returns.get(rid)
    if ret is None:
        raise err("ERR_NOT_FOUND", "return not found")
    if ret["status"] != "ESCALATED":
        raise err("ERR_INVALID_STATE", "return not in ESCALATED")
    body = body_or_empty()
    check_version(ret, body)
    ret["status"] = "REQUESTED"
    touch(ret)
    # Close linked WorkOrder
    from ..domain.work_orders import close_workorder_for_return_if_any
    close_workorder_for_return_if_any(ret["id"])
    return success(_view(ret))
