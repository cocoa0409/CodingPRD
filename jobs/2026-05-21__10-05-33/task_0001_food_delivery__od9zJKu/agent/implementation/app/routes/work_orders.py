from __future__ import annotations

from flask import Blueprint, g

from .. import projections, resolvers
from ..auth import require_role
from ..entities import bump, init_versioned
from ..envelope import (
    err_forbidden,
    err_invalid_state,
    err_not_found,
    err_related_return_unresolved,
    err_validation,
    success,
)
from ..store import store
from ..validators import get_json, optional_str, require_str

bp = Blueprint("work_orders", __name__)


WO_CATEGORIES = {
    "DELIVERY_LATE",
    "FOOD_QUALITY",
    "MISSING_ITEM",
    "RIDER_BEHAVIOR",
    "RESTAURANT_BEHAVIOR",
    "PAYMENT_ISSUE",
    "OTHER",
}
ROLE_TO_OPENED_BY = {
    "Customer": "CUSTOMER",
    "Rider": "RIDER",
    "Restaurant": "RESTAURANT",
    "CustomerService": "CUSTOMER_SERVICE",
    "PlatformAdmin": "CUSTOMER_SERVICE",  # platform admin opens as CS-equivalent
}


def _serialize(w: dict) -> dict:
    return projections.work_order(w)


@bp.route("/api/work-orders", methods=["POST"])
def open_work_order():
    require_role("Customer", "Rider", "Restaurant", "CustomerService", "PlatformAdmin")
    body = get_json()
    category = body.get("category")
    if category not in WO_CATEGORIES:
        raise err_validation("category must be a valid value")
    related_order_id = body.get("related_order_id")
    related_return_id = body.get("related_return_id")
    if related_order_id is not None:
        if not isinstance(related_order_id, str) or related_order_id not in store.orders:
            raise err_not_found(f"Order '{related_order_id}' not found")
    if related_return_id is not None:
        if not isinstance(related_return_id, str) or related_return_id not in store.returns:
            raise err_not_found(f"Return '{related_return_id}' not found")
    # Role -> opened_by_role mapping. Spec lists CUSTOMER/RIDER/RESTAURANT/CUSTOMER_SERVICE
    opened_by_role = ROLE_TO_OPENED_BY[g.user_role]
    opened_by_id = g.user_id
    # If role implies an entity, identity match: opened_by_id must be the caller's user id.
    # Spec says opened_by_id is the opener's identifier — for Customer/Rider/Restaurant it's the
    # entity id; for CS it's the opaque CS operator id. So we use g.user_id directly.
    # Customer/Rider/Restaurant roles must reference an existing entity:
    if g.user_role == "Customer" and g.user_id not in store.customers:
        raise err_not_found("Customer not found")
    if g.user_role == "Rider" and g.user_id not in store.riders:
        raise err_not_found("Rider not found")
    if g.user_role == "Restaurant" and g.user_id not in store.restaurants:
        raise err_not_found("Restaurant not found")
    wo = init_versioned("WorkOrder")
    wo.update(
        {
            "opened_by_role": opened_by_role,
            "opened_by_id": opened_by_id,
            "category": category,
            "related_order_id": related_order_id,
            "related_return_id": related_return_id,
            "status": "OPEN",
            "resolution_notes": None,
            "assigned_cs_user_id": None,
        }
    )
    store.work_orders[wo["id"]] = wo
    return success(_serialize(wo), status=201)


@bp.route("/api/work-orders/<wid>", methods=["GET"])
def read_work_order(wid: str):
    require_role("PlatformAdmin", "CustomerService", "Customer", "Rider", "Restaurant")
    w = resolvers.work_order(wid)
    # Identity gate
    if g.user_role == "Customer":
        if w["opened_by_role"] != "CUSTOMER" or g.user_id != w["opened_by_id"]:
            raise err_forbidden("Customer cannot view this work order")
    if g.user_role == "Rider":
        if w["opened_by_role"] != "RIDER" or g.user_id != w["opened_by_id"]:
            raise err_forbidden("Rider cannot view this work order")
    if g.user_role == "Restaurant":
        if w["opened_by_role"] != "RESTAURANT" or g.user_id != w["opened_by_id"]:
            raise err_forbidden("Restaurant cannot view this work order")
    return success(_serialize(w))


@bp.route("/api/work-orders/<wid>/assign", methods=["POST"])
def assign_wo(wid: str):
    require_role("CustomerService", "PlatformAdmin")
    w = resolvers.work_order(wid)
    if w["status"] != "OPEN":
        raise err_invalid_state(f"Cannot assign work order in state {w['status']}")
    w["status"] = "UNDER_REVIEW"
    w["assigned_cs_user_id"] = g.user_id
    bump(w)
    return success(_serialize(w))


@bp.route("/api/work-orders/<wid>/request-info", methods=["POST"])
def request_info(wid: str):
    require_role("CustomerService", "PlatformAdmin")
    w = resolvers.work_order(wid)
    if w["status"] != "UNDER_REVIEW":
        raise err_invalid_state(f"Cannot request info in state {w['status']}")
    w["status"] = "AWAITING_INFO"
    bump(w)
    return success(_serialize(w))


@bp.route("/api/work-orders/<wid>/submit-info", methods=["POST"])
def submit_info(wid: str):
    require_role("Customer", "Rider", "Restaurant")
    w = resolvers.work_order(wid)
    if g.user_id != w["opened_by_id"]:
        raise err_forbidden("Only the opener can submit info")
    if w["status"] != "AWAITING_INFO":
        raise err_invalid_state(f"Cannot submit info in state {w['status']}")
    w["status"] = "UNDER_REVIEW"
    bump(w)
    return success(_serialize(w))


@bp.route("/api/work-orders/<wid>/escalate", methods=["POST"])
def escalate_wo(wid: str):
    require_role("CustomerService", "PlatformAdmin")
    w = resolvers.work_order(wid)
    if w["status"] != "UNDER_REVIEW":
        raise err_invalid_state(f"Cannot escalate in state {w['status']}")
    w["status"] = "ESCALATED"
    bump(w)
    return success(_serialize(w))


@bp.route("/api/work-orders/<wid>/resolve", methods=["POST"])
def resolve_wo(wid: str):
    require_role("CustomerService", "PlatformAdmin")
    w = resolvers.work_order(wid)
    if w["status"] not in ("UNDER_REVIEW", "ESCALATED"):
        raise err_invalid_state(f"Cannot resolve in state {w['status']}")
    if not w.get("assigned_cs_user_id"):
        raise err_invalid_state("Work order must be assigned before resolution")
    # Related return gating
    if w.get("related_return_id"):
        related = store.returns.get(w["related_return_id"])
        if related and related["status"] in ("REQUESTED", "ESCALATED"):
            raise err_related_return_unresolved()
    body = get_json(required=False)
    notes = optional_str(body, "resolution_notes", max_len=2000) if body else None
    w["status"] = "RESOLVED"
    w["resolution_notes"] = notes or w.get("resolution_notes")
    bump(w)
    return success(_serialize(w))


@bp.route("/api/work-orders/<wid>/close", methods=["POST"])
def close_wo(wid: str):
    require_role("CustomerService", "PlatformAdmin")
    w = resolvers.work_order(wid)
    if w["status"] != "RESOLVED":
        raise err_invalid_state(f"Cannot close in state {w['status']}")
    w["status"] = "CLOSED"
    bump(w)
    return success(_serialize(w))
