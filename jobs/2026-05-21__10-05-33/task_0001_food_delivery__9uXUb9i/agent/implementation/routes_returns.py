"""Return / refund endpoints (PRD §3.9)."""
from __future__ import annotations

from flask import Blueprint, g

from auth import require_roles
from common import get_json_body, require_int
from envelope import success
from errors import ApiError
from serializers import serialize_return
import store
from store import gen_id, iso_z, lock, now


bp = Blueprint("returns", __name__, url_prefix="/api/returns")


def _find_return(rid: str) -> dict:
    r = store.returns_.get(rid)
    if not r:
        raise ApiError("ERR_NOT_FOUND", "Return not found.")
    return r


@bp.get("/<rid>")
@require_roles("PlatformAdmin", "Customer", "Restaurant", "CustomerService")
def read_return(rid: str):
    r = _find_return(rid)
    order = store.orders[r["order_id"]]
    if g.role == "Customer" and g.user_id != order["customer_id"]:
        raise ApiError("ERR_FORBIDDEN", "Customer identity mismatch.")
    if g.role == "Restaurant" and g.user_id != order["restaurant_id"]:
        raise ApiError("ERR_FORBIDDEN", "Restaurant identity mismatch.")
    return success(serialize_return(r))


@bp.post("/<rid>/approve")
@require_roles("CustomerService")
def approve_return(rid: str):
    r = _find_return(rid)
    if r["status"] not in ("REQUESTED", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE", "Return cannot be approved from current state.")
    body = get_json_body()
    approved = require_int(body, "approved_refund_cents")
    order = store.orders[r["order_id"]]
    if approved < 1 or approved > order["subtotal_cents"] or approved > r["requested_refund_cents"]:
        raise ApiError("ERR_REFUND_AMOUNT_INVALID", "approved_refund_cents out of range.")

    customer = store.customers[order["customer_id"]]
    rest = store.restaurants[order["restaurant_id"]]

    with lock():
        t = now()
        r["status"] = "APPROVED"
        r["approved_refund_cents"] = approved
        r["reviewer_cs_user_id"] = g.user_id
        r["updated_at"] = iso_z(t)
        r["version"] += 1

        order["status"] = "REFUNDED"
        if approved < order["subtotal_cents"]:
            order["payment_status"] = "PARTIALLY_REFUNDED"
        else:
            order["payment_status"] = "FULLY_REFUNDED"
        order["updated_at"] = iso_z(t)
        order["version"] += 1

        customer["credit_balance_cents"] += approved

        rest["pending_settlement_cents"] -= approved
        rest["updated_at"] = iso_z(t)
        rest["version"] += 1

        # ABUSIVE_RETURN fine: trust_score < 0.5 and reason QUALITY_ISSUE.
        # Per PRD §3.11 a waive "restores" the customer's credit balance, which
        # only makes sense if fine creation debits it. We debit at creation and
        # credit back on waive.
        if customer["trust_score"] < 0.5 and r["reason"] == "QUALITY_ISSUE":
            fid = gen_id()
            store.fines[fid] = {
                "id": fid,
                "subject_type": "CUSTOMER",
                "subject_id": customer["id"],
                "reason": "ABUSIVE_RETURN",
                "amount_cents": approved,
                "settlement_status": "PENDING",
                "order_id": order["id"],
                "created_at": iso_z(t),
            }
            customer["credit_balance_cents"] -= approved

        customer["updated_at"] = iso_z(t)
        customer["version"] += 1

        # Close any open WorkOrder linked to this return.
        for w in store.work_orders.values():
            if w.get("related_return_id") == r["id"] and w["status"] not in ("RESOLVED", "CLOSED"):
                # auto-close via no-op: PRD only describes auto-close on REOPEN.
                # But the work order can be resolved/closed manually; nothing to do here.
                pass
    return success(serialize_return(r))


@bp.post("/<rid>/reject")
@require_roles("CustomerService")
def reject_return(rid: str):
    r = _find_return(rid)
    if r["status"] not in ("REQUESTED", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE", "Return cannot be rejected from current state.")
    order = store.orders[r["order_id"]]
    with lock():
        t = now()
        r["status"] = "REJECTED"
        r["reviewer_cs_user_id"] = g.user_id
        r["updated_at"] = iso_z(t)
        r["version"] += 1
        # Order reverts from REFUND_REQUESTED -> DELIVERED.
        if order["status"] == "REFUND_REQUESTED":
            order["status"] = "DELIVERED"
            order["updated_at"] = iso_z(t)
            order["version"] += 1
    return success(serialize_return(r))


@bp.post("/<rid>/escalate")
@require_roles("CustomerService")
def escalate_return(rid: str):
    r = _find_return(rid)
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Only REQUESTED returns can be escalated.")
    with lock():
        t = now()
        r["status"] = "ESCALATED"
        r["updated_at"] = iso_z(t)
        r["version"] += 1
        # Open a linked work order.
        wid = gen_id()
        store.work_orders[wid] = {
            "id": wid,
            "opened_by_role": "CUSTOMER_SERVICE",
            "opened_by_id": g.user_id,
            "category": "OTHER",
            "related_order_id": r["order_id"],
            "related_return_id": r["id"],
            "resolution_notes": None,
            "assigned_cs_user_id": None,
            "status": "OPEN",
            "created_at": iso_z(t),
            "updated_at": iso_z(t),
            "version": 1,
        }
    return success(serialize_return(r))


@bp.post("/<rid>/reopen")
@require_roles("CustomerService")
def reopen_return(rid: str):
    r = _find_return(rid)
    if r["status"] != "ESCALATED":
        raise ApiError("ERR_INVALID_STATE", "Only ESCALATED returns can be reopened.")
    with lock():
        t = now()
        r["status"] = "REQUESTED"
        r["updated_at"] = iso_z(t)
        r["version"] += 1
        # Close linked work order
        for w in store.work_orders.values():
            if w.get("related_return_id") == r["id"] and w["status"] not in ("CLOSED",):
                w["status"] = "CLOSED"
                w["updated_at"] = iso_z(t)
                w["version"] += 1
    return success(serialize_return(r))
