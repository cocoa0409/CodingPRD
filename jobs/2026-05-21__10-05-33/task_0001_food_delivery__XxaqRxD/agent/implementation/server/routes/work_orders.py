"""Work-order endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from ..auth import require_role
from ..envelope import success_object
from ..errors import ApiError
from ..ids import new_uuid
from ..serializers import work_order_out
from ..validation import ensure_dict, optional_str, require_str


bp = Blueprint("work_orders", __name__, url_prefix="/api")


_CATEGORIES = {
    "DELIVERY_LATE",
    "FOOD_QUALITY",
    "MISSING_ITEM",
    "RIDER_BEHAVIOR",
    "RESTAURANT_BEHAVIOR",
    "PAYMENT_ISSUE",
    "OTHER",
}

_ROLES_TO_OPENER = {
    "Customer": "CUSTOMER",
    "Rider": "RIDER",
    "Restaurant": "RESTAURANT",
    "CustomerService": "CUSTOMER_SERVICE",
    "PlatformAdmin": "CUSTOMER_SERVICE",  # admin opens on behalf — recorded as CS
}


@bp.post("/work-orders")
def open_work_order():
    require_role("Customer", "Rider", "Restaurant", "CustomerService", "PlatformAdmin")
    store = g.store
    body = ensure_dict(request.get_json(silent=True) or {})
    category = require_str(body, "category")
    if category not in _CATEGORIES:
        raise ApiError("ERR_VALIDATION", "invalid category")
    related_order_id = optional_str(body, "related_order_id")
    related_return_id = optional_str(body, "related_return_id")
    with store.lock:
        if related_order_id and related_order_id not in store.orders:
            raise ApiError("ERR_NOT_FOUND")
        if related_return_id and related_return_id not in store.returns:
            raise ApiError("ERR_NOT_FOUND")
        opened_by_role = _ROLES_TO_OPENER[g.user_role]
        opened_by_id = g.user_id
        wid = new_uuid()
        now_iso = store.now_iso()
        wo = {
            "id": wid,
            "opened_by_role": opened_by_role,
            "opened_by_id": opened_by_id,
            "category": category,
            "related_order_id": related_order_id,
            "related_return_id": related_return_id,
            "status": "OPEN",
            "resolution_notes": None,
            "assigned_cs_user_id": None,
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
        }
        store.work_orders[wid] = wo
        return success_object(store.clock, work_order_out(wo), status=201)


@bp.get("/work-orders/<wid>")
def read_work_order(wid: str):
    require_role("PlatformAdmin", "CustomerService", "Customer", "Rider", "Restaurant")
    store = g.store
    wo = store.work_orders.get(wid)
    if not wo:
        raise ApiError("ERR_NOT_FOUND")
    # Visibility: non-opaque roles see only their own opener-marked tickets.
    if g.user_role in ("Customer", "Rider", "Restaurant"):
        if wo["opened_by_id"] != g.user_id:
            raise ApiError("ERR_FORBIDDEN")
    return success_object(store.clock, work_order_out(wo))


@bp.post("/work-orders/<wid>/assign")
def assign_work_order(wid: str):
    require_role("CustomerService", "PlatformAdmin")
    store = g.store
    with store.lock:
        wo = store.work_orders.get(wid)
        if not wo:
            raise ApiError("ERR_NOT_FOUND")
        if wo["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE")
        wo["assigned_cs_user_id"] = g.user_id
        wo["status"] = "UNDER_REVIEW"
        wo["version"] += 1
        wo["updated_at"] = store.now_iso()
        return success_object(store.clock, work_order_out(wo))


@bp.post("/work-orders/<wid>/request-info")
def request_info(wid: str):
    require_role("CustomerService", "PlatformAdmin")
    store = g.store
    with store.lock:
        wo = store.work_orders.get(wid)
        if not wo:
            raise ApiError("ERR_NOT_FOUND")
        if wo["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE")
        wo["status"] = "AWAITING_INFO"
        wo["version"] += 1
        wo["updated_at"] = store.now_iso()
        return success_object(store.clock, work_order_out(wo))


@bp.post("/work-orders/<wid>/submit-info")
def submit_info(wid: str):
    require_role("Customer", "Rider", "Restaurant")
    store = g.store
    with store.lock:
        wo = store.work_orders.get(wid)
        if not wo:
            raise ApiError("ERR_NOT_FOUND")
        if wo["opened_by_id"] != g.user_id:
            raise ApiError("ERR_FORBIDDEN")
        if wo["status"] != "AWAITING_INFO":
            raise ApiError("ERR_INVALID_STATE")
        wo["status"] = "UNDER_REVIEW"
        wo["version"] += 1
        wo["updated_at"] = store.now_iso()
        return success_object(store.clock, work_order_out(wo))


@bp.post("/work-orders/<wid>/resolve")
def resolve_work_order(wid: str):
    require_role("CustomerService", "PlatformAdmin")
    store = g.store
    body = ensure_dict(request.get_json(silent=True) or {})
    notes = require_str(body, "resolution_notes", max_len=2000)
    with store.lock:
        wo = store.work_orders.get(wid)
        if not wo:
            raise ApiError("ERR_NOT_FOUND")
        if wo["status"] not in ("UNDER_REVIEW", "ESCALATED"):
            raise ApiError("ERR_INVALID_STATE")
        if wo["assigned_cs_user_id"] is None:
            raise ApiError("ERR_INVALID_STATE")
        # Gate on linked Return status.
        if wo.get("related_return_id"):
            r = store.returns.get(wo["related_return_id"])
            if r is None:
                raise ApiError("ERR_NOT_FOUND")
            if r["status"] not in ("APPROVED", "REJECTED"):
                raise ApiError("ERR_RELATED_RETURN_UNRESOLVED")
        wo["resolution_notes"] = notes
        wo["status"] = "RESOLVED"
        wo["version"] += 1
        wo["updated_at"] = store.now_iso()
        return success_object(store.clock, work_order_out(wo))


@bp.post("/work-orders/<wid>/escalate")
def escalate_work_order(wid: str):
    require_role("CustomerService", "PlatformAdmin")
    store = g.store
    with store.lock:
        wo = store.work_orders.get(wid)
        if not wo:
            raise ApiError("ERR_NOT_FOUND")
        if wo["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE")
        wo["status"] = "ESCALATED"
        wo["version"] += 1
        wo["updated_at"] = store.now_iso()
        return success_object(store.clock, work_order_out(wo))


@bp.post("/work-orders/<wid>/close")
def close_work_order(wid: str):
    require_role("CustomerService", "PlatformAdmin")
    store = g.store
    with store.lock:
        wo = store.work_orders.get(wid)
        if not wo:
            raise ApiError("ERR_NOT_FOUND")
        if wo["status"] != "RESOLVED":
            raise ApiError("ERR_INVALID_STATE")
        wo["status"] = "CLOSED"
        wo["version"] += 1
        wo["updated_at"] = store.now_iso()
        return success_object(store.clock, work_order_out(wo))
