from flask import Blueprint

from ..auth import require_role
from ..envelope import success, created
from ..errors import err
from ..repository import base_versioned, touch, check_version, body_or_empty
from ..store import store

bp = Blueprint("work_orders", __name__)

_OPEN_ROLES = {"Customer", "Rider", "Restaurant", "CustomerService", "PlatformAdmin"}
_ROLE_TO_OPENED = {
    "Customer": "CUSTOMER",
    "Rider": "RIDER",
    "Restaurant": "RESTAURANT",
    "CustomerService": "CUSTOMER_SERVICE",
    "PlatformAdmin": "CUSTOMER_SERVICE",
}
_VALID_CATEGORIES = {
    "DELIVERY_LATE", "FOOD_QUALITY", "MISSING_ITEM",
    "RIDER_BEHAVIOR", "RESTAURANT_BEHAVIOR", "PAYMENT_ISSUE", "OTHER",
}


def _view(wo):
    return {k: wo.get(k) for k in (
        "id", "opened_by_role", "opened_by_id", "category",
        "related_order_id", "related_return_id",
        "status", "assigned_cs_user_id", "resolution_notes",
        "created_at", "updated_at", "version",
    )}


@bp.post("/api/work-orders")
def open_workorder():
    uid, role = require_role(*_OPEN_ROLES)
    body = body_or_empty()
    category = body.get("category")
    if category not in _VALID_CATEGORIES:
        raise err("ERR_VALIDATION", "invalid category")
    related_order_id = body.get("related_order_id")
    related_return_id = body.get("related_return_id")
    if related_order_id is not None:
        if related_order_id not in store.orders:
            raise err("ERR_NOT_FOUND", "related_order_id not found")
    if related_return_id is not None:
        if related_return_id not in store.returns:
            raise err("ERR_NOT_FOUND", "related_return_id not found")
    opened_by_role = _ROLE_TO_OPENED[role]
    wo = base_versioned()
    wo.update({
        "opened_by_role": opened_by_role,
        "opened_by_id": uid,
        "category": category,
        "related_order_id": related_order_id,
        "related_return_id": related_return_id,
        "status": "OPEN",
        "assigned_cs_user_id": None,
        "resolution_notes": None,
    })
    store.work_orders[wo["id"]] = wo
    return created(_view(wo))


@bp.get("/api/work-orders/<wid>")
def get_workorder(wid):
    uid, role = require_role("PlatformAdmin", "CustomerService", "Customer", "Rider", "Restaurant")
    wo = store.work_orders.get(wid)
    if wo is None:
        raise err("ERR_NOT_FOUND", "work order not found")
    if role in ("Customer", "Rider", "Restaurant"):
        if wo.get("opened_by_id") != uid:
            raise err("ERR_FORBIDDEN", "not your work order")
    return success(_view(wo))


@bp.post("/api/work-orders/<wid>/assign")
def assign_workorder(wid):
    uid, role = require_role("CustomerService", "PlatformAdmin")
    wo = store.work_orders.get(wid)
    if wo is None:
        raise err("ERR_NOT_FOUND", "work order not found")
    if wo["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "not in OPEN")
    body = body_or_empty()
    check_version(wo, body)
    wo["status"] = "UNDER_REVIEW"
    wo["assigned_cs_user_id"] = uid
    touch(wo)
    return success(_view(wo))


@bp.post("/api/work-orders/<wid>/request-info")
def request_info(wid):
    uid, role = require_role("CustomerService", "PlatformAdmin")
    wo = store.work_orders.get(wid)
    if wo is None:
        raise err("ERR_NOT_FOUND", "work order not found")
    if wo["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "not in UNDER_REVIEW")
    body = body_or_empty()
    check_version(wo, body)
    wo["status"] = "AWAITING_INFO"
    touch(wo)
    return success(_view(wo))


@bp.post("/api/work-orders/<wid>/submit-info")
def submit_info(wid):
    uid, role = require_role("Customer", "Rider", "Restaurant")
    wo = store.work_orders.get(wid)
    if wo is None:
        raise err("ERR_NOT_FOUND", "work order not found")
    if wo.get("opened_by_id") != uid:
        raise err("ERR_FORBIDDEN", "not your work order")
    if wo["status"] != "AWAITING_INFO":
        raise err("ERR_INVALID_STATE", "not in AWAITING_INFO")
    body = body_or_empty()
    check_version(wo, body)
    wo["status"] = "UNDER_REVIEW"
    touch(wo)
    return success(_view(wo))


@bp.post("/api/work-orders/<wid>/escalate")
def escalate_workorder(wid):
    uid, role = require_role("CustomerService", "PlatformAdmin")
    wo = store.work_orders.get(wid)
    if wo is None:
        raise err("ERR_NOT_FOUND", "work order not found")
    if wo["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "not in UNDER_REVIEW")
    body = body_or_empty()
    check_version(wo, body)
    wo["status"] = "ESCALATED"
    touch(wo)
    return success(_view(wo))


@bp.post("/api/work-orders/<wid>/resolve")
def resolve_workorder(wid):
    uid, role = require_role("CustomerService", "PlatformAdmin")
    wo = store.work_orders.get(wid)
    if wo is None:
        raise err("ERR_NOT_FOUND", "work order not found")
    if wo["status"] not in ("UNDER_REVIEW", "ESCALATED"):
        raise err("ERR_INVALID_STATE", "not in UNDER_REVIEW/ESCALATED")
    if wo.get("assigned_cs_user_id") is None:
        raise err("ERR_INVALID_STATE", "not assigned")
    body = body_or_empty()
    notes = body.get("resolution_notes")
    if not isinstance(notes, str) or not notes.strip():
        raise err("ERR_VALIDATION", "resolution_notes required")
    # Cross-entity gating: linked Return must be APPROVED or REJECTED
    if wo.get("related_return_id"):
        ret = store.returns.get(wo["related_return_id"])
        if ret is None or ret["status"] in ("REQUESTED", "ESCALATED"):
            raise err("ERR_RELATED_RETURN_UNRESOLVED", "linked return is unresolved")
    check_version(wo, body)
    wo["status"] = "RESOLVED"
    wo["resolution_notes"] = notes
    touch(wo)
    return success(_view(wo))


@bp.post("/api/work-orders/<wid>/close")
def close_workorder(wid):
    uid, role = require_role("CustomerService", "PlatformAdmin")
    wo = store.work_orders.get(wid)
    if wo is None:
        raise err("ERR_NOT_FOUND", "work order not found")
    if wo["status"] != "RESOLVED":
        raise err("ERR_INVALID_STATE", "not in RESOLVED")
    body = body_or_empty()
    check_version(wo, body)
    wo["status"] = "CLOSED"
    touch(wo)
    return success(_view(wo))
