"""Work order endpoints (PRD §3.10)."""
from __future__ import annotations

from flask import Blueprint, g

from auth import require_roles
from common import get_json_body, optional_str, require_str
from envelope import success
from errors import ApiError
from serializers import serialize_work_order
import store
from store import gen_id, iso_z, lock, now


bp = Blueprint("work_orders", __name__, url_prefix="/api/work-orders")


_VALID_CATEGORIES = {
    "DELIVERY_LATE",
    "FOOD_QUALITY",
    "MISSING_ITEM",
    "RIDER_BEHAVIOR",
    "RESTAURANT_BEHAVIOR",
    "PAYMENT_ISSUE",
    "OTHER",
}


_ROLE_TO_OPEN = {
    "Customer": "CUSTOMER",
    "Rider": "RIDER",
    "Restaurant": "RESTAURANT",
    "CustomerService": "CUSTOMER_SERVICE",
    "PlatformAdmin": "CUSTOMER_SERVICE",  # Admin acts as a CS opener
}


def _find_work_order(wid: str) -> dict:
    w = store.work_orders.get(wid)
    if not w:
        raise ApiError("ERR_NOT_FOUND", "Work order not found.")
    return w


@bp.post("")
@require_roles("Customer", "Rider", "Restaurant", "CustomerService", "PlatformAdmin")
def open_work_order():
    body = get_json_body()
    category = require_str(body, "category")
    if category not in _VALID_CATEGORIES:
        raise ApiError("ERR_VALIDATION", "Invalid category.")
    related_order_id = optional_str(body, "related_order_id")
    related_return_id = optional_str(body, "related_return_id")
    if related_order_id and related_order_id not in store.orders:
        raise ApiError("ERR_NOT_FOUND", "related_order_id not found.")
    if related_return_id and related_return_id not in store.returns_:
        raise ApiError("ERR_NOT_FOUND", "related_return_id not found.")

    # Identity binding for non-CS/Admin roles
    opened_by_role = _ROLE_TO_OPEN[g.role]
    opened_by_id = g.user_id
    if g.role == "Customer" and g.user_id not in store.customers:
        raise ApiError("ERR_FORBIDDEN", "Customer identity mismatch.")
    if g.role == "Rider" and g.user_id not in store.riders:
        raise ApiError("ERR_FORBIDDEN", "Rider identity mismatch.")
    if g.role == "Restaurant" and g.user_id not in store.restaurants:
        raise ApiError("ERR_FORBIDDEN", "Restaurant identity mismatch.")

    with lock():
        t = now()
        wid = gen_id()
        w = {
            "id": wid,
            "opened_by_role": opened_by_role,
            "opened_by_id": opened_by_id,
            "category": category,
            "related_order_id": related_order_id,
            "related_return_id": related_return_id,
            "resolution_notes": None,
            "assigned_cs_user_id": None,
            "status": "OPEN",
            "created_at": iso_z(t),
            "updated_at": iso_z(t),
            "version": 1,
        }
        store.work_orders[wid] = w
    return success(serialize_work_order(w), status=201)


@bp.get("/<wid>")
@require_roles("PlatformAdmin", "CustomerService", "Customer", "Rider", "Restaurant")
def read_work_order(wid: str):
    w = _find_work_order(wid)
    if g.role in ("Customer", "Rider", "Restaurant"):
        if g.user_id != w["opened_by_id"]:
            raise ApiError("ERR_FORBIDDEN", "Identity mismatch.")
    return success(serialize_work_order(w))


@bp.post("/<wid>/assign")
@require_roles("CustomerService", "PlatformAdmin")
def assign_work_order(wid: str):
    w = _find_work_order(wid)
    if w["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only OPEN tickets can be claimed.")
    with lock():
        w["status"] = "UNDER_REVIEW"
        w["assigned_cs_user_id"] = g.user_id
        w["updated_at"] = iso_z(now())
        w["version"] += 1
    return success(serialize_work_order(w))


@bp.post("/<wid>/request-info")
@require_roles("CustomerService", "PlatformAdmin")
def request_info(wid: str):
    w = _find_work_order(wid)
    if w["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Only UNDER_REVIEW tickets can request info.")
    with lock():
        w["status"] = "AWAITING_INFO"
        w["updated_at"] = iso_z(now())
        w["version"] += 1
    return success(serialize_work_order(w))


@bp.post("/<wid>/submit-info")
@require_roles("Customer", "Rider", "Restaurant")
def submit_info(wid: str):
    w = _find_work_order(wid)
    if g.user_id != w["opened_by_id"]:
        raise ApiError("ERR_FORBIDDEN", "Only the opener may submit info.")
    if w["status"] != "AWAITING_INFO":
        raise ApiError("ERR_INVALID_STATE", "Ticket is not AWAITING_INFO.")
    with lock():
        w["status"] = "UNDER_REVIEW"
        w["updated_at"] = iso_z(now())
        w["version"] += 1
    return success(serialize_work_order(w))


@bp.post("/<wid>/resolve")
@require_roles("CustomerService", "PlatformAdmin")
def resolve_work_order(wid: str):
    w = _find_work_order(wid)
    if w["status"] not in ("UNDER_REVIEW", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE", "Only UNDER_REVIEW or ESCALATED can be resolved.")
    if w["assigned_cs_user_id"] is None:
        raise ApiError("ERR_INVALID_STATE", "assigned_cs_user_id must be set before resolve.")
    body = get_json_body()
    notes = require_str(body, "resolution_notes")
    # Cross-entity gating: linked return must be APPROVED/REJECTED.
    if w.get("related_return_id"):
        rret = store.returns_.get(w["related_return_id"])
        if rret and rret["status"] not in ("APPROVED", "REJECTED"):
            raise ApiError("ERR_RELATED_RETURN_UNRESOLVED", "Linked return is not yet resolved.")
    with lock():
        w["status"] = "RESOLVED"
        w["resolution_notes"] = notes
        w["updated_at"] = iso_z(now())
        w["version"] += 1
    return success(serialize_work_order(w))


@bp.post("/<wid>/escalate")
@require_roles("CustomerService", "PlatformAdmin")
def escalate_work_order(wid: str):
    w = _find_work_order(wid)
    if w["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Only UNDER_REVIEW tickets can be escalated.")
    with lock():
        w["status"] = "ESCALATED"
        w["updated_at"] = iso_z(now())
        w["version"] += 1
    return success(serialize_work_order(w))


@bp.post("/<wid>/close")
@require_roles("CustomerService", "PlatformAdmin")
def close_work_order(wid: str):
    w = _find_work_order(wid)
    if w["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE", "Only RESOLVED tickets can be closed.")
    with lock():
        w["status"] = "CLOSED"
        w["updated_at"] = iso_z(now())
        w["version"] += 1
    return success(serialize_work_order(w))
