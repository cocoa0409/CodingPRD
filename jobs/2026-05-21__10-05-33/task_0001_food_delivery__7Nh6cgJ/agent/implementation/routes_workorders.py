"""Work order endpoints."""

from __future__ import annotations

from auth import require_role
from envelope import success
from errors import APIError
from resources import make_versioned, touch
from store import STORE
from validation import get_body, opt_str, require_str

VALID_CATEGORIES = {"DELIVERY_LATE", "FOOD_QUALITY", "MISSING_ITEM", "RIDER_BEHAVIOR",
                    "RESTAURANT_BEHAVIOR", "PAYMENT_ISSUE", "OTHER"}
VALID_OPENED_BY = {"CUSTOMER", "RIDER", "RESTAURANT", "CUSTOMER_SERVICE", "PLATFORM_ADMIN"}
ROLE_TO_OPENED_BY = {
    "Customer": "CUSTOMER",
    "Rider": "RIDER",
    "Restaurant": "RESTAURANT",
    "CustomerService": "CUSTOMER_SERVICE",
    "PlatformAdmin": "PLATFORM_ADMIN",
}


def _serialize(w: dict) -> dict:
    return {
        "id": w["id"],
        "opened_by_role": w["opened_by_role"],
        "opened_by_id": w["opened_by_id"],
        "category": w["category"],
        "related_order_id": w.get("related_order_id"),
        "related_return_id": w.get("related_return_id"),
        "assigned_cs_user_id": w.get("assigned_cs_user_id"),
        "resolution_notes": w.get("resolution_notes"),
        "status": w["status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def register(app):
    @app.post("/api/work-orders")
    def open_work_order():
        user_id, role = require_role({"Customer", "Rider", "Restaurant", "CustomerService", "PlatformAdmin"})
        body = get_body()
        category = require_str(body, "category")
        if category not in VALID_CATEGORIES:
            raise APIError("ERR_VALIDATION", "Invalid category.")
        opened_by_role = ROLE_TO_OPENED_BY[role]
        opened_by_id = user_id
        related_order_id = opt_str(body, "related_order_id")
        related_return_id = opt_str(body, "related_return_id")
        with STORE.lock:
            if related_order_id and related_order_id not in STORE.orders:
                raise APIError("ERR_NOT_FOUND", "No such order.")
            if related_return_id and related_return_id not in STORE.returns:
                raise APIError("ERR_NOT_FOUND", "No such return.")
            wo = make_versioned({
                "opened_by_role": opened_by_role,
                "opened_by_id": opened_by_id,
                "category": category,
                "related_order_id": related_order_id,
                "related_return_id": related_return_id,
                "assigned_cs_user_id": None,
                "resolution_notes": None,
                "status": "OPEN",
            })
            STORE.work_orders[wo["id"]] = wo
            return success(_serialize(wo), status=201)

    @app.get("/api/work-orders/<wid>")
    def read_work_order(wid: str):
        user_id, role = require_role({"PlatformAdmin", "CustomerService", "Customer", "Rider", "Restaurant"})
        with STORE.lock:
            w = STORE.work_orders.get(wid)
            if w is None:
                raise APIError("ERR_NOT_FOUND", "No such work order.")
            if role in ("Customer", "Rider", "Restaurant"):
                expected = ROLE_TO_OPENED_BY[role]
                if w["opened_by_role"] != expected or w["opened_by_id"] != user_id:
                    raise APIError("ERR_FORBIDDEN")
            return success(_serialize(w))

    @app.post("/api/work-orders/<wid>/assign")
    def assign_work_order(wid: str):
        user_id, _ = require_role({"CustomerService", "PlatformAdmin"})
        with STORE.lock:
            w = STORE.work_orders.get(wid)
            if w is None:
                raise APIError("ERR_NOT_FOUND", "No such work order.")
            if w["status"] != "OPEN":
                raise APIError("ERR_INVALID_STATE", "Only OPEN work orders can be claimed.")
            w["assigned_cs_user_id"] = user_id
            w["status"] = "UNDER_REVIEW"
            touch(w)
            return success(_serialize(w))

    @app.post("/api/work-orders/<wid>/request-info")
    def request_info(wid: str):
        require_role({"CustomerService", "PlatformAdmin"})
        with STORE.lock:
            w = STORE.work_orders.get(wid)
            if w is None:
                raise APIError("ERR_NOT_FOUND", "No such work order.")
            if w["status"] != "UNDER_REVIEW":
                raise APIError("ERR_INVALID_STATE", "Work order must be UNDER_REVIEW.")
            w["status"] = "AWAITING_INFO"
            touch(w)
            return success(_serialize(w))

    @app.post("/api/work-orders/<wid>/submit-info")
    def submit_info(wid: str):
        user_id, role = require_role({"Customer", "Rider", "Restaurant"})
        with STORE.lock:
            w = STORE.work_orders.get(wid)
            if w is None:
                raise APIError("ERR_NOT_FOUND", "No such work order.")
            expected = ROLE_TO_OPENED_BY[role]
            if w["opened_by_role"] != expected or w["opened_by_id"] != user_id:
                raise APIError("ERR_FORBIDDEN")
            if w["status"] != "AWAITING_INFO":
                raise APIError("ERR_INVALID_STATE", "Work order is not AWAITING_INFO.")
            w["status"] = "UNDER_REVIEW"
            touch(w)
            return success(_serialize(w))

    @app.post("/api/work-orders/<wid>/escalate")
    def escalate_wo(wid: str):
        require_role({"CustomerService", "PlatformAdmin"})
        with STORE.lock:
            w = STORE.work_orders.get(wid)
            if w is None:
                raise APIError("ERR_NOT_FOUND", "No such work order.")
            if w["status"] != "UNDER_REVIEW":
                raise APIError("ERR_INVALID_STATE", "Work order must be UNDER_REVIEW.")
            w["status"] = "ESCALATED"
            touch(w)
            return success(_serialize(w))

    @app.post("/api/work-orders/<wid>/resolve")
    def resolve_wo(wid: str):
        require_role({"CustomerService", "PlatformAdmin"})
        body = get_body()
        with STORE.lock:
            w = STORE.work_orders.get(wid)
            if w is None:
                raise APIError("ERR_NOT_FOUND", "No such work order.")
            if w["status"] not in ("UNDER_REVIEW", "ESCALATED"):
                raise APIError("ERR_INVALID_STATE", "Work order is not in a resolvable state.")
            if not w.get("assigned_cs_user_id"):
                raise APIError("ERR_INVALID_STATE", "Work order has no assigned CS user.")
            notes = require_str(body, "resolution_notes", min_length=1, max_length=5000)
            # Related return gating (priority 13).
            if w.get("related_return_id"):
                ret = STORE.returns.get(w["related_return_id"])
                if ret is None or ret["status"] not in ("APPROVED", "REJECTED"):
                    raise APIError("ERR_RELATED_RETURN_UNRESOLVED")
            w["resolution_notes"] = notes
            w["status"] = "RESOLVED"
            touch(w)
            return success(_serialize(w))

    @app.post("/api/work-orders/<wid>/close")
    def close_wo(wid: str):
        require_role({"CustomerService", "PlatformAdmin"})
        with STORE.lock:
            w = STORE.work_orders.get(wid)
            if w is None:
                raise APIError("ERR_NOT_FOUND", "No such work order.")
            if w["status"] != "RESOLVED":
                raise APIError("ERR_INVALID_STATE", "Only RESOLVED work orders can be closed.")
            w["status"] = "CLOSED"
            touch(w)
            return success(_serialize(w))
