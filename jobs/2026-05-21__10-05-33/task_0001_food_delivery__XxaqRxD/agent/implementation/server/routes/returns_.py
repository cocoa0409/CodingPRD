"""Return / refund endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from ..auth import require_role
from ..clock import parse_iso
from ..envelope import success_object
from ..errors import ApiError
from ..ids import new_uuid
from ..serializers import return_out
from ..validation import ensure_dict, require_int, require_str


bp = Blueprint("returns", __name__, url_prefix="/api")


_REASONS = {"QUALITY_ISSUE", "WRONG_ITEM", "LATE", "OTHER"}


@bp.post("/orders/<oid>/returns")
def open_return(oid: str):
    require_role("Customer")
    store = g.store
    body = ensure_dict(request.get_json(silent=True) or {})
    with store.lock:
        order = store.orders.get(oid)
        if not order:
            raise ApiError("ERR_NOT_FOUND")
        if g.user_id != order["customer_id"]:
            raise ApiError("ERR_FORBIDDEN")
        reason = require_str(body, "reason")
        if reason not in _REASONS:
            raise ApiError("ERR_VALIDATION", "invalid reason")
        # Duplicate return check precedes the order's state precondition because
        # a non-DELIVERED status here would be the *consequence* of the duplicate.
        for r in store.returns.values():
            if r["order_id"] == oid and r["status"] in ("REQUESTED", "APPROVED", "ESCALATED"):
                raise ApiError("ERR_DUPLICATE_RETURN")
        if order["status"] != "DELIVERED":
            raise ApiError("ERR_INVALID_STATE")
        # Temporal window (step 9).
        delivered_at = order.get("actual_delivery_time")
        if delivered_at is None:
            raise ApiError("ERR_INVALID_STATE")
        if (store.clock.now() - parse_iso(delivered_at)).total_seconds() > 24 * 3600:
            raise ApiError("ERR_RETURN_WINDOW_EXPIRED")
        # Fiscal range (step 10).
        amt = require_int(body, "requested_refund_cents")
        if amt < 1 or amt > order["subtotal_cents"]:
            raise ApiError("ERR_REFUND_AMOUNT_INVALID")

        rid = new_uuid()
        now_iso = store.now_iso()
        r = {
            "id": rid,
            "order_id": oid,
            "reason": reason,
            "requested_refund_cents": amt,
            "approved_refund_cents": None,
            "status": "REQUESTED",
            "reviewer_cs_user_id": None,
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
        }
        store.returns[rid] = r
        order["status"] = "REFUND_REQUESTED"
        order["version"] += 1
        order["updated_at"] = now_iso
        return success_object(store.clock, return_out(r), status=201)


@bp.get("/returns/<rid>")
def read_return(rid: str):
    require_role("PlatformAdmin", "Customer", "Restaurant", "CustomerService")
    store = g.store
    r = store.returns.get(rid)
    if not r:
        raise ApiError("ERR_NOT_FOUND")
    order = store.orders[r["order_id"]]
    if g.user_role == "Customer" and g.user_id != order["customer_id"]:
        raise ApiError("ERR_FORBIDDEN")
    if g.user_role == "Restaurant" and g.user_id != order["restaurant_id"]:
        raise ApiError("ERR_FORBIDDEN")
    return success_object(store.clock, return_out(r))


@bp.post("/returns/<rid>/approve")
def approve_return(rid: str):
    require_role("CustomerService")
    store = g.store
    body = ensure_dict(request.get_json(silent=True) or {})
    with store.lock:
        r = store.returns.get(rid)
        if not r:
            raise ApiError("ERR_NOT_FOUND")
        if r["status"] not in ("REQUESTED", "ESCALATED"):
            raise ApiError("ERR_INVALID_STATE")
        order = store.orders[r["order_id"]]
        amt = require_int(body, "approved_refund_cents")
        if amt < 1 or amt > order["subtotal_cents"] or amt > r["requested_refund_cents"]:
            raise ApiError("ERR_REFUND_AMOUNT_INVALID")
        now_iso = store.now_iso()
        r["status"] = "APPROVED"
        r["approved_refund_cents"] = amt
        r["reviewer_cs_user_id"] = g.user_id
        r["version"] += 1
        r["updated_at"] = now_iso
        # Order: REFUND_REQUESTED -> REFUNDED
        order["status"] = "REFUNDED"
        order["payment_status"] = (
            "FULLY_REFUNDED" if amt == order["subtotal_cents"] else "PARTIALLY_REFUNDED"
        )
        order["version"] += 1
        order["updated_at"] = now_iso
        # Customer credit
        customer = store.customers[order["customer_id"]]
        customer["credit_balance_cents"] += amt
        customer["version"] += 1
        customer["updated_at"] = now_iso
        # Restaurant settlement decrement
        restaurant = store.restaurants[order["restaurant_id"]]
        restaurant["pending_settlement_cents"] -= amt
        restaurant["version"] += 1
        restaurant["updated_at"] = now_iso
        # Abusive-return fine if trust_score < 0.5 and reason is QUALITY_ISSUE
        if customer["trust_score"] < 0.5 and r["reason"] == "QUALITY_ISSUE":
            from ..services.delivery import _create_fine

            _create_fine(
                store,
                subject_type="CUSTOMER",
                subject_id=customer["id"],
                reason="ABUSIVE_RETURN",
                amount_cents=amt,
                order_id=order["id"],
            )
            # The PRD doesn't specify a ledger-debit mechanic for customer fines
            # beyond crediting credit_balance_cents. We deduct the fine from the
            # just-issued credit so the net credit aligns with the abuse penalty.
            customer["credit_balance_cents"] = max(0, customer["credit_balance_cents"] - amt)
            customer["version"] += 1
            customer["updated_at"] = now_iso
        # Auto-close any linked WorkOrder created at escalation time.
        for wo in store.work_orders.values():
            if wo.get("related_return_id") == rid and wo["status"] not in ("RESOLVED", "CLOSED"):
                # Per the spec, escalating a return opens a WO; reopening (not approve/reject)
                # closes it automatically. Approve/reject leave the WO open so the operator
                # can resolve via the standard flow. We don't auto-close on approve here.
                pass
        return success_object(store.clock, return_out(r))


@bp.post("/returns/<rid>/reject")
def reject_return(rid: str):
    require_role("CustomerService")
    store = g.store
    with store.lock:
        r = store.returns.get(rid)
        if not r:
            raise ApiError("ERR_NOT_FOUND")
        if r["status"] not in ("REQUESTED", "ESCALATED"):
            raise ApiError("ERR_INVALID_STATE")
        order = store.orders[r["order_id"]]
        now_iso = store.now_iso()
        r["status"] = "REJECTED"
        r["reviewer_cs_user_id"] = g.user_id
        r["version"] += 1
        r["updated_at"] = now_iso
        order["status"] = "DELIVERED"
        order["version"] += 1
        order["updated_at"] = now_iso
        return success_object(store.clock, return_out(r))


@bp.post("/returns/<rid>/escalate")
def escalate_return(rid: str):
    require_role("CustomerService")
    store = g.store
    with store.lock:
        r = store.returns.get(rid)
        if not r:
            raise ApiError("ERR_NOT_FOUND")
        if r["status"] != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE")
        now_iso = store.now_iso()
        r["status"] = "ESCALATED"
        r["version"] += 1
        r["updated_at"] = now_iso
        # Open a WorkOrder linked to this return.
        wid = new_uuid()
        wo = {
            "id": wid,
            "opened_by_role": "CUSTOMER_SERVICE",
            "opened_by_id": g.user_id,
            "category": "OTHER",
            "related_order_id": r["order_id"],
            "related_return_id": rid,
            "status": "OPEN",
            "resolution_notes": None,
            "assigned_cs_user_id": None,
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
        }
        store.work_orders[wid] = wo
        return success_object(store.clock, return_out(r))


@bp.post("/returns/<rid>/reopen")
def reopen_return(rid: str):
    require_role("CustomerService")
    store = g.store
    with store.lock:
        r = store.returns.get(rid)
        if not r:
            raise ApiError("ERR_NOT_FOUND")
        if r["status"] != "ESCALATED":
            raise ApiError("ERR_INVALID_STATE")
        now_iso = store.now_iso()
        r["status"] = "REQUESTED"
        r["version"] += 1
        r["updated_at"] = now_iso
        # Close the linked WorkOrder.
        for wo in store.work_orders.values():
            if wo.get("related_return_id") == rid and wo["status"] not in ("CLOSED",):
                wo["status"] = "CLOSED"
                wo["version"] += 1
                wo["updated_at"] = now_iso
        return success_object(store.clock, return_out(r))
