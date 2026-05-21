"""Return endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from auth import require_role
from clock import CLOCK
from envelope import success
from errors import APIError
from fines_logic import create_customer_fine
from resources import make_versioned, touch
from store import STORE
from validation import get_body, require_int, require_str

VALID_REASONS = {"QUALITY_ISSUE", "WRONG_ITEM", "LATE", "OTHER"}


def _parse_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _serialize(r: dict) -> dict:
    return {
        "id": r["id"],
        "order_id": r["order_id"],
        "reason": r["reason"],
        "requested_refund_cents": r["requested_refund_cents"],
        "approved_refund_cents": r.get("approved_refund_cents"),
        "status": r["status"],
        "reviewer_cs_user_id": r.get("reviewer_cs_user_id"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def register(app):
    @app.post("/api/orders/<oid>/returns")
    def open_return(oid: str):
        user_id, _ = require_role({"Customer"})
        body = get_body()
        with STORE.lock:
            o = STORE.orders.get(oid)
            if o is None:
                raise APIError("ERR_NOT_FOUND", "No such order.")
            if user_id != o["customer_id"]:
                raise APIError("ERR_FORBIDDEN")
            # Duplicate return check fires before state precondition: when an open Return
            # exists, the order is in REFUND_REQUESTED, which would otherwise read as an
            # invalid-state failure. PRD §3.9 specifies ERR_DUPLICATE_RETURN here.
            for existing in STORE.returns.values():
                if existing["order_id"] == oid and existing["status"] in ("REQUESTED", "APPROVED", "ESCALATED"):
                    raise APIError("ERR_DUPLICATE_RETURN")
            # Allow DELIVERED, or REFUNDED with no live return (i.e., previous return was REJECTED).
            if o["status"] not in ("DELIVERED",):
                raise APIError("ERR_INVALID_STATE", "Order must be DELIVERED to open a return.")
            # Temporal window check.
            actual = o.get("actual_delivery_time")
            if actual is not None:
                delivered = _parse_iso(actual)
                if (CLOCK.now() - delivered) > timedelta(hours=24):
                    raise APIError("ERR_RETURN_WINDOW_EXPIRED")
            reason = require_str(body, "reason")
            if reason not in VALID_REASONS:
                raise APIError("ERR_VALIDATION", "Invalid reason.")
            requested = require_int(body, "requested_refund_cents")
            if requested < 1 or requested > int(o["subtotal_cents"]):
                raise APIError("ERR_REFUND_AMOUNT_INVALID")
            ret = make_versioned({
                "order_id": oid,
                "reason": reason,
                "requested_refund_cents": requested,
                "approved_refund_cents": None,
                "status": "REQUESTED",
                "reviewer_cs_user_id": None,
            })
            STORE.returns[ret["id"]] = ret
            o["status"] = "REFUND_REQUESTED"
            touch(o)
            return success(_serialize(ret), status=201)

    @app.get("/api/returns/<rid>")
    def read_return(rid: str):
        user_id, role = require_role({"PlatformAdmin", "Customer", "Restaurant", "CustomerService"})
        with STORE.lock:
            ret = STORE.returns.get(rid)
            if ret is None:
                raise APIError("ERR_NOT_FOUND", "No such return.")
            order = STORE.orders.get(ret["order_id"])
            if order is None:
                raise APIError("ERR_NOT_FOUND", "No such order.")
            if role == "Customer" and user_id != order["customer_id"]:
                raise APIError("ERR_FORBIDDEN")
            if role == "Restaurant" and user_id != order["restaurant_id"]:
                raise APIError("ERR_FORBIDDEN")
            return success(_serialize(ret))

    @app.post("/api/returns/<rid>/approve")
    def approve_return(rid: str):
        user_id, _ = require_role({"CustomerService"})
        body = get_body()
        with STORE.lock:
            ret = STORE.returns.get(rid)
            if ret is None:
                raise APIError("ERR_NOT_FOUND", "No such return.")
            if ret["status"] not in ("REQUESTED", "ESCALATED"):
                raise APIError("ERR_INVALID_STATE", "Return is not in REQUESTED or ESCALATED.")
            order = STORE.orders[ret["order_id"]]
            approved = require_int(body, "approved_refund_cents")
            if approved < 1 or approved > int(order["subtotal_cents"]) or approved > int(ret["requested_refund_cents"]):
                raise APIError("ERR_REFUND_AMOUNT_INVALID")
            # OCC on Return.
            from resources import check_version
            check_version(ret, body.get("version"))

            ret["status"] = "APPROVED"
            ret["approved_refund_cents"] = approved
            ret["reviewer_cs_user_id"] = user_id
            touch(ret)

            order["status"] = "REFUNDED"
            order["payment_status"] = "FULLY_REFUNDED" if approved == int(order["subtotal_cents"]) else "PARTIALLY_REFUNDED"
            touch(order)

            customer = STORE.customers[order["customer_id"]]
            customer["credit_balance_cents"] = int(customer["credit_balance_cents"]) + int(approved)
            touch(customer)

            restaurant = STORE.restaurants[order["restaurant_id"]]
            restaurant["pending_settlement_cents"] = int(restaurant["pending_settlement_cents"]) - int(approved)
            touch(restaurant)

            # Abusive return fine.
            if customer["trust_score"] < 0.5 and ret["reason"] == "QUALITY_ISSUE":
                create_customer_fine(customer["id"], "ABUSIVE_RETURN", approved)

            # Close any linked work orders.
            for wo in STORE.work_orders.values():
                if wo.get("related_return_id") == ret["id"] and wo["status"] not in ("RESOLVED", "CLOSED"):
                    # Per §3.10: an escalated return that's brought back to REQUESTED auto-closes its WO.
                    # For approval, we don't force-close; leave the WO state as-is unless ESCALATED.
                    pass
            return success(_serialize(ret))

    @app.post("/api/returns/<rid>/reject")
    def reject_return(rid: str):
        user_id, _ = require_role({"CustomerService"})
        with STORE.lock:
            ret = STORE.returns.get(rid)
            if ret is None:
                raise APIError("ERR_NOT_FOUND", "No such return.")
            if ret["status"] not in ("REQUESTED", "ESCALATED"):
                raise APIError("ERR_INVALID_STATE", "Return is not in REQUESTED or ESCALATED.")
            ret["status"] = "REJECTED"
            ret["reviewer_cs_user_id"] = user_id
            touch(ret)
            order = STORE.orders[ret["order_id"]]
            order["status"] = "DELIVERED"
            touch(order)
            return success(_serialize(ret))

    @app.post("/api/returns/<rid>/escalate")
    def escalate_return(rid: str):
        user_id, _ = require_role({"CustomerService"})
        with STORE.lock:
            ret = STORE.returns.get(rid)
            if ret is None:
                raise APIError("ERR_NOT_FOUND", "No such return.")
            if ret["status"] != "REQUESTED":
                raise APIError("ERR_INVALID_STATE", "Only REQUESTED returns can be escalated.")
            ret["status"] = "ESCALATED"
            touch(ret)
            # Open a WorkOrder linked via related_return_id.
            wo = make_versioned({
                "opened_by_role": "CUSTOMER_SERVICE",
                "opened_by_id": user_id,
                "category": "OTHER",
                "related_order_id": ret["order_id"],
                "related_return_id": ret["id"],
                "assigned_cs_user_id": None,
                "resolution_notes": None,
                "status": "OPEN",
            })
            STORE.work_orders[wo["id"]] = wo
            return success(_serialize(ret))

    @app.post("/api/returns/<rid>/reopen")
    def reopen_return(rid: str):
        require_role({"CustomerService"})
        with STORE.lock:
            ret = STORE.returns.get(rid)
            if ret is None:
                raise APIError("ERR_NOT_FOUND", "No such return.")
            if ret["status"] != "ESCALATED":
                raise APIError("ERR_INVALID_STATE", "Only ESCALATED returns can be reopened.")
            ret["status"] = "REQUESTED"
            touch(ret)
            # Auto-close any linked WO
            for wo in STORE.work_orders.values():
                if wo.get("related_return_id") == ret["id"] and wo["status"] not in ("CLOSED",):
                    wo["status"] = "CLOSED"
                    touch(wo)
            return success(_serialize(ret))
