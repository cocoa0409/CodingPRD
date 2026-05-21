"""Return / refund flow."""
from datetime import datetime, timedelta, timezone
from flask import request, g

from ..auth import parse_headers, require_role
from ..clock import format_iso
from ..envelope import success
from ..errors import fail
from ..ids import new_uuid
from ..resource import stamp_new, bump
from ..server import store, clock


REASONS = {"QUALITY_ISSUE", "WRONG_ITEM", "LATE", "OTHER"}


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def open_return(oid):
    user_id, role = parse_headers()
    require_role("Customer")
    o = store.orders.get(oid)
    if not o:
        raise fail("ERR_NOT_FOUND")
    if user_id != o["customer_id"]:
        raise fail("ERR_FORBIDDEN")
    # Duplicate return: open against an order that already has a live return is a uniqueness
    # invariant. Surfacing ERR_DUPLICATE_RETURN here gives the client a clearer signal than the
    # cascaded REFUND_REQUESTED state would.
    for r in store.returns.values():
        if r["order_id"] == oid and r["status"] in ("REQUESTED", "APPROVED", "ESCALATED"):
            raise fail("ERR_DUPLICATE_RETURN")
    if o["status"] not in ("DELIVERED",):
        raise fail("ERR_INVALID_STATE")
    # 24-hour window
    actual = _parse_iso(o["actual_delivery_time"])
    if (clock.now() - actual) > timedelta(hours=24):
        raise fail("ERR_RETURN_WINDOW_EXPIRED")
    body = request.get_json(silent=True) or {}
    reason = body.get("reason")
    if reason not in REASONS:
        raise fail("ERR_VALIDATION", "reason invalid")
    requested = body.get("requested_refund_cents")
    if not isinstance(requested, int) or isinstance(requested, bool):
        raise fail("ERR_REFUND_AMOUNT_INVALID")
    if requested < 1 or requested > o["subtotal_cents"]:
        raise fail("ERR_REFUND_AMOUNT_INVALID")
    rec = stamp_new()
    rec.update({
        "order_id": oid,
        "reason": reason,
        "requested_refund_cents": requested,
        "approved_refund_cents": None,
        "reviewer_cs_user_id": None,
        "status": "REQUESTED",
    })
    store.returns[rec["id"]] = rec
    # Order cascade
    o["status"] = "REFUND_REQUESTED"
    bump(o)
    return success(rec, status=201)


def approve_return(rid):
    user_id, role = parse_headers()
    require_role("CustomerService")
    ret = store.returns.get(rid)
    if not ret:
        raise fail("ERR_NOT_FOUND")
    if ret["status"] not in ("REQUESTED", "ESCALATED"):
        raise fail("ERR_INVALID_STATE")
    o = store.orders[ret["order_id"]]
    body = request.get_json(silent=True) or {}
    approved = body.get("approved_refund_cents")
    if not isinstance(approved, int) or isinstance(approved, bool):
        raise fail("ERR_REFUND_AMOUNT_INVALID")
    if approved < 1 or approved > o["subtotal_cents"] or approved > ret["requested_refund_cents"]:
        raise fail("ERR_REFUND_AMOUNT_INVALID")
    # Apply cascade
    ret["status"] = "APPROVED"
    ret["approved_refund_cents"] = approved
    ret["reviewer_cs_user_id"] = user_id
    bump(ret)
    # Order
    o["status"] = "REFUNDED"
    o["payment_status"] = "FULLY_REFUNDED" if approved == o["subtotal_cents"] else "PARTIALLY_REFUNDED"
    bump(o)
    # Customer credit
    customer = store.customers[o["customer_id"]]
    customer["credit_balance_cents"] += approved
    # Trust score: a successful return uses up some trust. PRD says it drops on abusive returns —
    # only fine creation drops the customer's trust on QUALITY_ISSUE + low trust; we keep this here
    # as a no-op for non-abusive returns.
    bump(customer)
    # Restaurant settlement decrement
    restaurant = store.restaurants[o["restaurant_id"]]
    restaurant["pending_settlement_cents"] -= approved
    bump(restaurant)
    # Abusive return fine
    if customer["trust_score"] < 0.5 and ret["reason"] == "QUALITY_ISSUE":
        from .fines import create_fine
        create_fine("CUSTOMER", customer["id"], "ABUSIVE_RETURN", approved)
    # Close any linked work order(s) that target this return — not specified, leave open.
    return success(ret)


def reject_return(rid):
    user_id, role = parse_headers()
    require_role("CustomerService")
    ret = store.returns.get(rid)
    if not ret:
        raise fail("ERR_NOT_FOUND")
    if ret["status"] not in ("REQUESTED", "ESCALATED"):
        raise fail("ERR_INVALID_STATE")
    ret["status"] = "REJECTED"
    ret["reviewer_cs_user_id"] = user_id
    bump(ret)
    # Order reverts from REFUND_REQUESTED to DELIVERED
    o = store.orders[ret["order_id"]]
    if o["status"] == "REFUND_REQUESTED":
        o["status"] = "DELIVERED"
        bump(o)
    return success(ret)


def escalate_return(rid):
    user_id, role = parse_headers()
    require_role("CustomerService")
    ret = store.returns.get(rid)
    if not ret:
        raise fail("ERR_NOT_FOUND")
    if ret["status"] != "REQUESTED":
        raise fail("ERR_INVALID_STATE")
    ret["status"] = "ESCALATED"
    bump(ret)
    # Open a linked WorkOrder
    from ..resource import stamp_new
    wo = stamp_new()
    wo.update({
        "opened_by_role": "CUSTOMER_SERVICE",
        "opened_by_id": user_id,
        "category": "OTHER",
        "related_order_id": ret["order_id"],
        "related_return_id": ret["id"],
        "status": "OPEN",
        "assigned_cs_user_id": None,
        "resolution_notes": None,
    })
    store.work_orders[wo["id"]] = wo
    return success(ret)


def reopen_return(rid):
    user_id, role = parse_headers()
    require_role("CustomerService")
    ret = store.returns.get(rid)
    if not ret:
        raise fail("ERR_NOT_FOUND")
    if ret["status"] != "ESCALATED":
        raise fail("ERR_INVALID_STATE")
    ret["status"] = "REQUESTED"
    bump(ret)
    # Close linked WorkOrder
    for wo in store.work_orders.values():
        if wo["related_return_id"] == ret["id"] and wo["status"] not in ("RESOLVED", "CLOSED"):
            wo["status"] = "CLOSED"
            bump(wo)
            break
    return success(ret)
