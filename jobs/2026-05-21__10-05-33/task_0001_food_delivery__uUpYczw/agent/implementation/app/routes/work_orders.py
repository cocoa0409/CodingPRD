"""Work order routes — open / read / assign / request-info / submit-info / escalate / resolve / close."""
from __future__ import annotations

from flask import Blueprint

from .. import cascade
from ..auth import require_role
from ..envelope import envelope_object, expect_json_body
from ..errors import ApiError
from ..ids import new_uuid
from ..store import get_clock, get_store
from ..validators import opt_str, req_str

bp = Blueprint("work_orders", __name__, url_prefix="/api")


CATEGORIES = {
    "DELIVERY_LATE", "FOOD_QUALITY", "MISSING_ITEM",
    "RIDER_BEHAVIOR", "RESTAURANT_BEHAVIOR", "PAYMENT_ISSUE", "OTHER",
}
OPENED_BY_ROLES = {"CUSTOMER", "RIDER", "RESTAURANT", "CUSTOMER_SERVICE"}


def _ensure_wo(store, wid):
    rec = store.work_orders.get(wid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", f"WorkOrder {wid} not found")
    return rec


@bp.post("/work-orders")
def open_wo():
    uid, role = require_role({"Customer", "Rider", "Restaurant", "CustomerService", "PlatformAdmin"})
    body = expect_json_body()
    opened_by_role = req_str(body, "opened_by_role")
    if opened_by_role not in OPENED_BY_ROLES:
        raise ApiError("ERR_VALIDATION", "invalid opened_by_role")
    opened_by_id = req_str(body, "opened_by_id")
    category = req_str(body, "category")
    if category not in CATEGORIES:
        raise ApiError("ERR_VALIDATION", "invalid category")

    # Identity match — opener-role/id must align with caller for non-CS/PA roles
    role_to_open_map = {
        "Customer": "CUSTOMER",
        "Rider": "RIDER",
        "Restaurant": "RESTAURANT",
        "CustomerService": "CUSTOMER_SERVICE",
        "PlatformAdmin": None,
    }
    expected_open = role_to_open_map.get(role)
    if role != "PlatformAdmin":
        if expected_open != opened_by_role:
            raise ApiError("ERR_FORBIDDEN", "opened_by_role must match caller role")
        if opened_by_id != uid:
            raise ApiError("ERR_FORBIDDEN", "opened_by_id must match X-User-ID")

    store = get_store()
    clock = get_clock()
    related_order_id = body.get("related_order_id")
    related_return_id = body.get("related_return_id")
    with store.lock:
        if related_order_id is not None:
            if related_order_id not in store.orders:
                raise ApiError("ERR_NOT_FOUND", "related_order_id not found")
        if related_return_id is not None:
            if related_return_id not in store.returns:
                raise ApiError("ERR_NOT_FOUND", "related_return_id not found")

        # If the opener role corresponds to a known entity, validate it exists.
        if opened_by_role == "CUSTOMER" and opened_by_id not in store.customers and role != "PlatformAdmin":
            raise ApiError("ERR_NOT_FOUND", "opened_by_id (customer) not found")
        if opened_by_role == "RIDER" and opened_by_id not in store.riders and role != "PlatformAdmin":
            raise ApiError("ERR_NOT_FOUND", "opened_by_id (rider) not found")
        if opened_by_role == "RESTAURANT" and opened_by_id not in store.restaurants and role != "PlatformAdmin":
            raise ApiError("ERR_NOT_FOUND", "opened_by_id (restaurant) not found")

        now = clock.now_iso()
        rec = {
            "id": new_uuid(),
            "opened_by_role": opened_by_role,
            "opened_by_id": opened_by_id,
            "category": category,
            "related_order_id": related_order_id,
            "related_return_id": related_return_id,
            "assigned_cs_user_id": None,
            "resolution_notes": None,
            "status": "OPEN",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.work_orders[rec["id"]] = rec
    return envelope_object(rec, status=201)


@bp.get("/work-orders/<wid>")
def read_wo(wid):
    uid, role = require_role({"PlatformAdmin", "CustomerService", "Customer", "Rider", "Restaurant"})
    store = get_store()
    with store.lock:
        rec = _ensure_wo(store, wid)
        # Opener can read their own ticket; CS/PA can read any.
        if role in {"Customer", "Rider", "Restaurant"}:
            if rec["opened_by_id"] != uid:
                raise ApiError("ERR_FORBIDDEN", "not your work order")
    return envelope_object(rec)


@bp.post("/work-orders/<wid>/assign")
def assign_wo(wid):
    uid, _ = require_role({"CustomerService", "PlatformAdmin"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        rec = _ensure_wo(store, wid)
        if rec["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "wo not OPEN")
        rec["assigned_cs_user_id"] = uid
        rec["status"] = "UNDER_REVIEW"
        cascade.touch(rec, clock)
    return envelope_object(rec)


@bp.post("/work-orders/<wid>/request-info")
def request_info_wo(wid):
    require_role({"CustomerService", "PlatformAdmin"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        rec = _ensure_wo(store, wid)
        if rec["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "wo not UNDER_REVIEW")
        rec["status"] = "AWAITING_INFO"
        cascade.touch(rec, clock)
    return envelope_object(rec)


@bp.post("/work-orders/<wid>/submit-info")
def submit_info_wo(wid):
    uid, _ = require_role({"Customer", "Rider", "Restaurant"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        rec = _ensure_wo(store, wid)
        if uid != rec["opened_by_id"]:
            raise ApiError("ERR_FORBIDDEN", "not your work order")
        if rec["status"] != "AWAITING_INFO":
            raise ApiError("ERR_INVALID_STATE", "wo not AWAITING_INFO")
        rec["status"] = "UNDER_REVIEW"
        cascade.touch(rec, clock)
    return envelope_object(rec)


@bp.post("/work-orders/<wid>/escalate")
def escalate_wo(wid):
    require_role({"CustomerService", "PlatformAdmin"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        rec = _ensure_wo(store, wid)
        if rec["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "wo not UNDER_REVIEW")
        rec["status"] = "ESCALATED"
        cascade.touch(rec, clock)
    return envelope_object(rec)


@bp.post("/work-orders/<wid>/resolve")
def resolve_wo(wid):
    require_role({"CustomerService", "PlatformAdmin"})
    body = expect_json_body()
    notes = req_str(body, "resolution_notes")
    store = get_store()
    clock = get_clock()
    with store.lock:
        rec = _ensure_wo(store, wid)
        if rec["status"] not in {"UNDER_REVIEW", "ESCALATED"}:
            raise ApiError("ERR_INVALID_STATE", "wo not resolvable")
        if rec["assigned_cs_user_id"] is None:
            raise ApiError("ERR_INVALID_STATE", "wo not claimed")
        if rec.get("related_return_id"):
            related = store.returns.get(rec["related_return_id"])
            if related and related["status"] in {"REQUESTED", "ESCALATED"}:
                raise ApiError("ERR_RELATED_RETURN_UNRESOLVED", "related return unresolved")
        rec["resolution_notes"] = notes
        rec["status"] = "RESOLVED"
        cascade.touch(rec, clock)
    return envelope_object(rec)


@bp.post("/work-orders/<wid>/close")
def close_wo(wid):
    require_role({"CustomerService", "PlatformAdmin"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        rec = _ensure_wo(store, wid)
        if rec["status"] != "RESOLVED":
            raise ApiError("ERR_INVALID_STATE", "wo not RESOLVED")
        rec["status"] = "CLOSED"
        cascade.touch(rec, clock)
    return envelope_object(rec)
