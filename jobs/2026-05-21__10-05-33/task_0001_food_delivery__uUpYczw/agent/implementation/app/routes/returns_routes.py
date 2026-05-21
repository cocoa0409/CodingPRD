"""Return routes — open / approve / reject / escalate / reopen."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

from .. import cascade
from ..auth import require_role
from ..clock import parse_iso
from ..envelope import envelope_object, expect_json_body
from ..errors import ApiError
from ..ids import new_uuid
from ..store import get_clock, get_store
from ..validators import req_int, req_str

bp = Blueprint("returns", __name__, url_prefix="/api")


RETURN_STATUSES = {"REQUESTED", "APPROVED", "REJECTED", "ESCALATED"}
REASONS = {"QUALITY_ISSUE", "WRONG_ITEM", "LATE", "OTHER"}


def _ensure_order(store, oid):
    rec = store.orders.get(oid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", f"Order {oid} not found")
    return rec


def _ensure_return(store, rid):
    rec = store.returns.get(rid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", f"Return {rid} not found")
    return rec


@bp.post("/orders/<oid>/returns")
def open_return(oid):
    uid, _ = require_role({"Customer"})
    body = expect_json_body()
    store = get_store()
    clock = get_clock()
    with store.lock:
        order = _ensure_order(store, oid)
        if uid != order["customer_id"]:
            raise ApiError("ERR_FORBIDDEN", "not your order")

        # Duplicate-return check fires before the state-machine check because
        # the order's REFUND_REQUESTED state is a downstream consequence of
        # the active return; the PRD example for ERR_DUPLICATE_RETURN is
        # precisely this case (§3.9).
        for r in store.returns.values():
            if r["order_id"] == oid and r["status"] in {"REQUESTED", "APPROVED", "ESCALATED"}:
                raise ApiError("ERR_DUPLICATE_RETURN", "active return exists")

        if order["status"] != "DELIVERED":
            raise ApiError("ERR_INVALID_STATE", "order not DELIVERED")

        # Temporal: within 24h of actual_delivery_time
        actual = parse_iso(order["actual_delivery_time"])
        if (clock.now_dt() - actual) > timedelta(hours=24):
            raise ApiError("ERR_RETURN_WINDOW_EXPIRED", "return window expired")

        # Refund amount
        amt = req_int(body, "requested_refund_cents")
        if amt < 1 or amt > order["subtotal_cents"]:
            raise ApiError("ERR_REFUND_AMOUNT_INVALID", "requested refund out of range")

        reason = req_str(body, "reason")
        if reason not in REASONS:
            raise ApiError("ERR_VALIDATION", "invalid reason")

        now_iso = clock.now_iso()
        rec = {
            "id": new_uuid(),
            "order_id": oid,
            "reason": reason,
            "requested_refund_cents": amt,
            "approved_refund_cents": None,
            "reviewer_cs_user_id": None,
            "status": "REQUESTED",
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
        }
        store.returns[rec["id"]] = rec
        order["status"] = "REFUND_REQUESTED"
        cascade.touch(order, clock)
    return envelope_object(rec, status=201)


@bp.get("/returns/<rid>")
def read_return(rid):
    uid, role = require_role({"PlatformAdmin", "Customer", "Restaurant", "CustomerService"})
    store = get_store()
    with store.lock:
        rec = _ensure_return(store, rid)
        order = store.orders[rec["order_id"]]
        if role == "Customer" and uid != order["customer_id"]:
            raise ApiError("ERR_FORBIDDEN", "not your return")
        if role == "Restaurant" and uid != order["restaurant_id"]:
            raise ApiError("ERR_FORBIDDEN", "not your return")
    return envelope_object(rec)


@bp.post("/returns/<rid>/approve")
def approve_return(rid):
    uid, _ = require_role({"CustomerService"})
    body = expect_json_body()
    store = get_store()
    clock = get_clock()
    with store.lock:
        rec = _ensure_return(store, rid)
        if rec["status"] not in {"REQUESTED", "ESCALATED"}:
            raise ApiError("ERR_INVALID_STATE", "return not REQUESTED/ESCALATED")
        order = store.orders[rec["order_id"]]
        amt = req_int(body, "approved_refund_cents")
        if amt < 1 or amt > order["subtotal_cents"] or amt > rec["requested_refund_cents"]:
            raise ApiError("ERR_REFUND_AMOUNT_INVALID", "approved refund out of range")

        # Apply state changes
        rec["status"] = "APPROVED"
        rec["approved_refund_cents"] = amt
        rec["reviewer_cs_user_id"] = uid
        cascade.touch(rec, clock)

        order["status"] = "REFUNDED"
        if amt == order["subtotal_cents"]:
            order["payment_status"] = "FULLY_REFUNDED"
        else:
            order["payment_status"] = "PARTIALLY_REFUNDED"
        cascade.touch(order, clock)

        customer = store.customers[order["customer_id"]]
        customer["credit_balance_cents"] += amt
        cascade.touch(customer, clock)

        restaurant = store.restaurants[order["restaurant_id"]]
        restaurant["pending_settlement_cents"] -= amt
        cascade.touch(restaurant, clock)

        # Abusive return fine
        if customer["trust_score"] < 0.5 and rec["reason"] == "QUALITY_ISSUE":
            fine = {
                "id": new_uuid(),
                "subject_type": "CUSTOMER",
                "subject_id": customer["id"],
                "reason": "ABUSIVE_RETURN",
                "amount_cents": amt,
                "settlement_status": "PENDING",
                "order_id": order["id"],
                "return_id": rec["id"],
                "created_at": clock.now_iso(),
            }
            store.fines[fine["id"]] = fine

        # Close any linked work order for this return.
        for wo in store.work_orders.values():
            if wo.get("related_return_id") == rec["id"] and wo["status"] not in {"RESOLVED", "CLOSED"}:
                # Approval doesn't auto-close — only reopen does that per PRD.
                pass

    return envelope_object(rec)


@bp.post("/returns/<rid>/reject")
def reject_return(rid):
    uid, _ = require_role({"CustomerService"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        rec = _ensure_return(store, rid)
        if rec["status"] not in {"REQUESTED", "ESCALATED"}:
            raise ApiError("ERR_INVALID_STATE", "return not REQUESTED/ESCALATED")
        order = store.orders[rec["order_id"]]
        rec["status"] = "REJECTED"
        rec["reviewer_cs_user_id"] = uid
        cascade.touch(rec, clock)
        order["status"] = "DELIVERED"
        cascade.touch(order, clock)
    return envelope_object(rec)


@bp.post("/returns/<rid>/escalate")
def escalate_return(rid):
    uid, _ = require_role({"CustomerService"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        rec = _ensure_return(store, rid)
        if rec["status"] != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE", "return not REQUESTED")
        rec["status"] = "ESCALATED"
        cascade.touch(rec, clock)
        # Auto-open a linked WorkOrder
        now_iso = clock.now_iso()
        wo = {
            "id": new_uuid(),
            "opened_by_role": "CUSTOMER_SERVICE",
            "opened_by_id": uid,
            "category": "OTHER",
            "related_order_id": rec["order_id"],
            "related_return_id": rec["id"],
            "assigned_cs_user_id": None,
            "resolution_notes": None,
            "status": "OPEN",
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
        }
        store.work_orders[wo["id"]] = wo
    return envelope_object(rec)


@bp.post("/returns/<rid>/reopen")
def reopen_return(rid):
    require_role({"CustomerService"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        rec = _ensure_return(store, rid)
        if rec["status"] != "ESCALATED":
            raise ApiError("ERR_INVALID_STATE", "return not ESCALATED")
        rec["status"] = "REQUESTED"
        cascade.touch(rec, clock)
        # Close the linked work order
        for wo in store.work_orders.values():
            if wo.get("related_return_id") == rec["id"] and wo["status"] not in {"CLOSED"}:
                wo["status"] = "CLOSED"
                cascade.touch(wo, clock)
    return envelope_object(rec)
