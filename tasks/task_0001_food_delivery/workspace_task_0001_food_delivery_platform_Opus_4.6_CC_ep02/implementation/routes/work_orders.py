from flask import Blueprint, request
from auth import require_roles
from errors import APIError
from models import (work_orders, orders, returns as returns_store, customers, riders,
                    restaurants, versioned_resource_base, touch, check_version)
from response_envelope import success_response

bp = Blueprint("work_orders", __name__)


def work_order_dict(wo):
    return {
        "id": wo["id"],
        "opened_by_role": wo["opened_by_role"],
        "opened_by_id": wo["opened_by_id"],
        "category": wo["category"],
        "related_order_id": wo["related_order_id"],
        "related_return_id": wo["related_return_id"],
        "assigned_cs_user_id": wo["assigned_cs_user_id"],
        "resolution_notes": wo["resolution_notes"],
        "status": wo["status"],
        "created_at": wo["created_at"],
        "updated_at": wo["updated_at"],
        "version": wo["version"],
    }


VALID_CATEGORIES = {
    "DELIVERY_LATE", "FOOD_QUALITY", "MISSING_ITEM", "RIDER_BEHAVIOR",
    "RESTAURANT_BEHAVIOR", "PAYMENT_ISSUE", "OTHER"
}

ROLE_TO_OPENED_BY = {
    "Customer": "CUSTOMER",
    "Rider": "RIDER",
    "Restaurant": "RESTAURANT",
    "CustomerService": "CUSTOMER_SERVICE",
    "PlatformAdmin": "PLATFORM_ADMIN",
}


@bp.route("/api/work-orders", methods=["POST"])
@require_roles("Customer", "Rider", "Restaurant", "CustomerService", "PlatformAdmin")
def create_work_order():
    data = request.get_json(force=True, silent=True) or {}

    opened_by_role = data.get("opened_by_role")
    if not opened_by_role:
        raise APIError("ERR_VALIDATION", "opened_by_role is required")

    opened_by_id = data.get("opened_by_id")
    if not opened_by_id:
        raise APIError("ERR_VALIDATION", "opened_by_id is required")

    category = data.get("category")
    if not category or category not in VALID_CATEGORIES:
        raise APIError("ERR_VALIDATION", f"category must be one of {', '.join(VALID_CATEGORIES)}")

    related_order_id = data.get("related_order_id")
    if related_order_id:
        if related_order_id not in orders:
            raise APIError("ERR_NOT_FOUND", "Related order not found")

    related_return_id = data.get("related_return_id")
    if related_return_id:
        if related_return_id not in returns_store:
            raise APIError("ERR_NOT_FOUND", "Related return not found")

    wo = versioned_resource_base()
    wo.update({
        "opened_by_role": opened_by_role,
        "opened_by_id": opened_by_id,
        "category": category,
        "related_order_id": related_order_id,
        "related_return_id": related_return_id,
        "assigned_cs_user_id": None,
        "resolution_notes": None,
        "status": "OPEN",
    })

    work_orders[wo["id"]] = wo
    return success_response(work_order_dict(wo), 201)


@bp.route("/api/work-orders/<wo_id>", methods=["GET"])
@require_roles("PlatformAdmin", "CustomerService", "Customer", "Rider", "Restaurant")
def get_work_order(wo_id):
    wo = work_orders.get(wo_id)
    if not wo:
        raise APIError("ERR_NOT_FOUND", "Work order not found")
    return success_response(work_order_dict(wo))


@bp.route("/api/work-orders/<wo_id>/assign", methods=["POST"])
@require_roles("CustomerService", "PlatformAdmin")
def assign_work_order(wo_id):
    wo = work_orders.get(wo_id)
    if not wo:
        raise APIError("ERR_NOT_FOUND", "Work order not found")

    if wo["status"] != "OPEN":
        raise APIError("ERR_INVALID_STATE", "Work order must be in OPEN to assign")

    wo["assigned_cs_user_id"] = request.user_id
    wo["status"] = "UNDER_REVIEW"
    touch(wo)
    return success_response(work_order_dict(wo))


@bp.route("/api/work-orders/<wo_id>/request-info", methods=["POST"])
@require_roles("CustomerService", "PlatformAdmin")
def request_info(wo_id):
    wo = work_orders.get(wo_id)
    if not wo:
        raise APIError("ERR_NOT_FOUND", "Work order not found")

    if wo["status"] != "UNDER_REVIEW":
        raise APIError("ERR_INVALID_STATE", "Work order must be in UNDER_REVIEW to request info")

    wo["status"] = "AWAITING_INFO"
    touch(wo)
    return success_response(work_order_dict(wo))


@bp.route("/api/work-orders/<wo_id>/submit-info", methods=["POST"])
@require_roles("Customer", "Rider", "Restaurant")
def submit_info(wo_id):
    wo = work_orders.get(wo_id)
    if not wo:
        raise APIError("ERR_NOT_FOUND", "Work order not found")

    if wo["status"] != "AWAITING_INFO":
        raise APIError("ERR_INVALID_STATE", "Work order must be in AWAITING_INFO to submit info")

    if wo["opened_by_id"] != request.user_id:
        raise APIError("ERR_FORBIDDEN", "Only the opener can submit info")

    wo["status"] = "UNDER_REVIEW"
    touch(wo)
    return success_response(work_order_dict(wo))


@bp.route("/api/work-orders/<wo_id>/escalate", methods=["POST"])
@require_roles("CustomerService", "PlatformAdmin")
def escalate_work_order(wo_id):
    wo = work_orders.get(wo_id)
    if not wo:
        raise APIError("ERR_NOT_FOUND", "Work order not found")

    if wo["status"] != "UNDER_REVIEW":
        raise APIError("ERR_INVALID_STATE", "Work order must be in UNDER_REVIEW to escalate")

    wo["status"] = "ESCALATED"
    touch(wo)
    return success_response(work_order_dict(wo))


@bp.route("/api/work-orders/<wo_id>/resolve", methods=["POST"])
@require_roles("CustomerService", "PlatformAdmin")
def resolve_work_order(wo_id):
    wo = work_orders.get(wo_id)
    if not wo:
        raise APIError("ERR_NOT_FOUND", "Work order not found")

    if wo["status"] not in ("UNDER_REVIEW", "ESCALATED"):
        raise APIError("ERR_INVALID_STATE", "Work order must be in UNDER_REVIEW or ESCALATED to resolve")

    if not wo["assigned_cs_user_id"]:
        raise APIError("ERR_INVALID_STATE", "Work order must have an assigned CS user to resolve")

    if wo.get("related_return_id"):
        ret = returns_store.get(wo["related_return_id"])
        if ret and ret["status"] in ("REQUESTED", "ESCALATED"):
            raise APIError("ERR_RELATED_RETURN_UNRESOLVED",
                            "Linked return must be resolved before closing the work order")

    data = request.get_json(force=True, silent=True) or {}
    resolution_notes = data.get("resolution_notes")

    wo["resolution_notes"] = resolution_notes
    wo["status"] = "RESOLVED"
    touch(wo)
    return success_response(work_order_dict(wo))


@bp.route("/api/work-orders/<wo_id>/close", methods=["POST"])
@require_roles("CustomerService", "PlatformAdmin")
def close_work_order(wo_id):
    wo = work_orders.get(wo_id)
    if not wo:
        raise APIError("ERR_NOT_FOUND", "Work order not found")

    if wo["status"] != "RESOLVED":
        raise APIError("ERR_INVALID_STATE", "Work order must be in RESOLVED to close")

    wo["status"] = "CLOSED"
    touch(wo)
    return success_response(work_order_dict(wo))
