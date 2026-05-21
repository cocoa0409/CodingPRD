"""Work-order endpoints."""
from flask import request, g

from ..auth import parse_headers, require_role
from ..envelope import success
from ..errors import fail
from ..resource import stamp_new, bump
from ..server import store


def register(app, prefix):
    app.add_url_rule("/api/work-orders", endpoint=f"{prefix}.create", view_func=create, methods=["POST"])
    app.add_url_rule("/api/work-orders/<wid>", endpoint=f"{prefix}.read", view_func=read, methods=["GET"])
    app.add_url_rule("/api/work-orders/<wid>/assign", endpoint=f"{prefix}.assign", view_func=assign, methods=["POST"])
    app.add_url_rule("/api/work-orders/<wid>/request-info", endpoint=f"{prefix}.request_info", view_func=request_info, methods=["POST"])
    app.add_url_rule("/api/work-orders/<wid>/submit-info", endpoint=f"{prefix}.submit_info", view_func=submit_info, methods=["POST"])
    app.add_url_rule("/api/work-orders/<wid>/resolve", endpoint=f"{prefix}.resolve", view_func=resolve, methods=["POST"])
    app.add_url_rule("/api/work-orders/<wid>/escalate", endpoint=f"{prefix}.escalate", view_func=escalate, methods=["POST"])
    app.add_url_rule("/api/work-orders/<wid>/close", endpoint=f"{prefix}.close", view_func=close, methods=["POST"])


CATEGORIES = {
    "DELIVERY_LATE", "FOOD_QUALITY", "MISSING_ITEM",
    "RIDER_BEHAVIOR", "RESTAURANT_BEHAVIOR", "PAYMENT_ISSUE", "OTHER",
}
ROLE_TO_OPENER = {
    "Customer": "CUSTOMER",
    "Rider": "RIDER",
    "Restaurant": "RESTAURANT",
    "CustomerService": "CUSTOMER_SERVICE",
    "PlatformAdmin": "PLATFORM_ADMIN",
}


def create():
    user_id, role = parse_headers()
    require_role("Customer", "Rider", "Restaurant", "CustomerService", "PlatformAdmin")
    body = request.get_json(silent=True) or {}
    category = body.get("category")
    if category not in CATEGORIES:
        raise fail("ERR_VALIDATION", "category invalid")
    related_order_id = body.get("related_order_id")
    related_return_id = body.get("related_return_id")
    if related_order_id is not None and related_order_id not in store.orders:
        raise fail("ERR_NOT_FOUND")
    if related_return_id is not None and related_return_id not in store.returns:
        raise fail("ERR_NOT_FOUND")

    opened_by_role = ROLE_TO_OPENER[role]
    # opened_by_id: bind to entity for Customer/Rider/Restaurant; opaque for CS/Admin
    opened_by_id = user_id
    if role == "Customer" and user_id not in store.customers:
        raise fail("ERR_FORBIDDEN")
    if role == "Rider" and user_id not in store.riders:
        raise fail("ERR_FORBIDDEN")
    if role == "Restaurant" and user_id not in store.restaurants:
        raise fail("ERR_FORBIDDEN")

    rec = stamp_new()
    rec.update({
        "opened_by_role": opened_by_role,
        "opened_by_id": opened_by_id,
        "category": category,
        "related_order_id": related_order_id,
        "related_return_id": related_return_id,
        "status": "OPEN",
        "assigned_cs_user_id": None,
        "resolution_notes": None,
    })
    store.work_orders[rec["id"]] = rec
    return success(rec, status=201)


def read(wid):
    user_id, role = parse_headers()
    require_role("PlatformAdmin", "CustomerService", "Customer", "Rider", "Restaurant")
    w = store.work_orders.get(wid)
    if not w:
        raise fail("ERR_NOT_FOUND")
    # Openers can only see their own; CS/Admin see all.
    if role in ("Customer", "Rider", "Restaurant") and user_id != w["opened_by_id"]:
        raise fail("ERR_FORBIDDEN")
    return success(w)


def _cs_load(wid):
    parse_headers()
    require_role("CustomerService", "PlatformAdmin")
    w = store.work_orders.get(wid)
    if not w:
        raise fail("ERR_NOT_FOUND")
    return w


def assign(wid):
    user_id, role = parse_headers()
    require_role("CustomerService", "PlatformAdmin")
    w = store.work_orders.get(wid)
    if not w:
        raise fail("ERR_NOT_FOUND")
    if w["status"] != "OPEN":
        raise fail("ERR_INVALID_STATE")
    w["status"] = "UNDER_REVIEW"
    w["assigned_cs_user_id"] = user_id
    bump(w)
    return success(w)


def request_info(wid):
    w = _cs_load(wid)
    if w["status"] != "UNDER_REVIEW":
        raise fail("ERR_INVALID_STATE")
    w["status"] = "AWAITING_INFO"
    bump(w)
    return success(w)


def submit_info(wid):
    user_id, role = parse_headers()
    require_role("Customer", "Rider", "Restaurant")
    w = store.work_orders.get(wid)
    if not w:
        raise fail("ERR_NOT_FOUND")
    if user_id != w["opened_by_id"]:
        raise fail("ERR_FORBIDDEN")
    if w["status"] != "AWAITING_INFO":
        raise fail("ERR_INVALID_STATE")
    w["status"] = "UNDER_REVIEW"
    bump(w)
    return success(w)


def resolve(wid):
    user_id, role = parse_headers()
    require_role("CustomerService", "PlatformAdmin")
    w = store.work_orders.get(wid)
    if not w:
        raise fail("ERR_NOT_FOUND")
    if w["status"] not in ("UNDER_REVIEW", "ESCALATED"):
        raise fail("ERR_INVALID_STATE")
    if w["assigned_cs_user_id"] is None:
        raise fail("ERR_INVALID_STATE")
    if w["related_return_id"]:
        ret = store.returns.get(w["related_return_id"])
        if ret and ret["status"] not in ("APPROVED", "REJECTED"):
            raise fail("ERR_RELATED_RETURN_UNRESOLVED")
    body = request.get_json(silent=True) or {}
    notes = body.get("resolution_notes")
    if not isinstance(notes, str) or not notes.strip():
        raise fail("ERR_VALIDATION", "resolution_notes required")
    w["status"] = "RESOLVED"
    w["resolution_notes"] = notes
    bump(w)
    return success(w)


def escalate(wid):
    w = _cs_load(wid)
    if w["status"] != "UNDER_REVIEW":
        raise fail("ERR_INVALID_STATE")
    w["status"] = "ESCALATED"
    bump(w)
    return success(w)


def close(wid):
    w = _cs_load(wid)
    if w["status"] != "RESOLVED":
        raise fail("ERR_INVALID_STATE")
    w["status"] = "CLOSED"
    bump(w)
    return success(w)
