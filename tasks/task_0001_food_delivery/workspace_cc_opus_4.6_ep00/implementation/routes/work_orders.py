from flask import Blueprint, request
from store import store
from models import make_versioned, touch, serialize
from middleware import check_role_permission
from response import success_response
from errors import (
    raise_error, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_VALIDATION, ERR_RELATED_RETURN_UNRESOLVED,
)

bp = Blueprint("work_orders", __name__)

VALID_CATEGORIES = {
    "DELIVERY_LATE", "FOOD_QUALITY", "MISSING_ITEM", "RIDER_BEHAVIOR",
    "RESTAURANT_BEHAVIOR", "PAYMENT_ISSUE", "OTHER",
}

VALID_OPENER_ROLES = {"CUSTOMER", "RIDER", "RESTAURANT", "CUSTOMER_SERVICE"}


@bp.route("/api/work-orders", methods=["POST"])
def create_work_order():
    check_role_permission({"Customer", "Rider", "Restaurant", "CustomerService", "PlatformAdmin"})
    data = request.get_json(force=True, silent=True) or {}

    opened_by_role = data.get("opened_by_role")
    if opened_by_role not in VALID_OPENER_ROLES:
        raise_error(ERR_VALIDATION, "opened_by_role must be one of CUSTOMER, RIDER, RESTAURANT, CUSTOMER_SERVICE")

    opened_by_id = data.get("opened_by_id")
    if not opened_by_id:
        raise_error(ERR_VALIDATION, "opened_by_id is required")

    category = data.get("category")
    if category not in VALID_CATEGORIES:
        raise_error(ERR_VALIDATION, f"category must be one of {', '.join(VALID_CATEGORIES)}")

    related_order_id = data.get("related_order_id")
    if related_order_id and not store.orders.get(related_order_id):
        raise_error(ERR_NOT_FOUND, "Related order not found")

    related_return_id = data.get("related_return_id")
    if related_return_id and not store.returns.get(related_return_id):
        raise_error(ERR_NOT_FOUND, "Related return not found")

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
    store.work_orders[wo["id"]] = wo
    return success_response(serialize(wo), 201)


@bp.route("/api/work-orders/<wo_id>", methods=["GET"])
def get_work_order(wo_id):
    check_role_permission({"PlatformAdmin", "CustomerService", "Customer", "Rider", "Restaurant"})
    wo = store.work_orders.get(wo_id)
    if not wo:
        raise_error(ERR_NOT_FOUND, "Work order not found")
    return success_response(serialize(wo))


@bp.route("/api/work-orders/<wo_id>/assign", methods=["POST"])
def assign_work_order(wo_id):
    check_role_permission({"CustomerService", "PlatformAdmin"})
    wo = store.work_orders.get(wo_id)
    if not wo:
        raise_error(ERR_NOT_FOUND, "Work order not found")

    if wo["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "Work order must be OPEN to assign")

    wo["assigned_cs_user_id"] = request.user_id
    wo["status"] = "UNDER_REVIEW"
    touch(wo)
    return success_response(serialize(wo))


@bp.route("/api/work-orders/<wo_id>/request-info", methods=["POST"])
def request_info(wo_id):
    check_role_permission({"CustomerService", "PlatformAdmin"})
    wo = store.work_orders.get(wo_id)
    if not wo:
        raise_error(ERR_NOT_FOUND, "Work order not found")

    if wo["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "Work order must be UNDER_REVIEW to request info")

    wo["status"] = "AWAITING_INFO"
    touch(wo)
    return success_response(serialize(wo))


@bp.route("/api/work-orders/<wo_id>/submit-info", methods=["POST"])
def submit_info(wo_id):
    check_role_permission({"Customer", "Rider", "Restaurant"})
    wo = store.work_orders.get(wo_id)
    if not wo:
        raise_error(ERR_NOT_FOUND, "Work order not found")

    if wo["status"] != "AWAITING_INFO":
        raise_error(ERR_INVALID_STATE, "Work order must be AWAITING_INFO to submit info")

    if request.user_id != wo["opened_by_id"]:
        raise_error(ERR_FORBIDDEN, "Only the opener can submit info")

    wo["status"] = "UNDER_REVIEW"
    touch(wo)
    return success_response(serialize(wo))


@bp.route("/api/work-orders/<wo_id>/resolve", methods=["POST"])
def resolve_work_order(wo_id):
    check_role_permission({"CustomerService", "PlatformAdmin"})
    wo = store.work_orders.get(wo_id)
    if not wo:
        raise_error(ERR_NOT_FOUND, "Work order not found")

    if wo["status"] not in ("UNDER_REVIEW", "ESCALATED"):
        raise_error(ERR_INVALID_STATE, "Work order must be UNDER_REVIEW or ESCALATED to resolve")

    if not wo["assigned_cs_user_id"]:
        raise_error(ERR_INVALID_STATE, "Work order must be assigned before resolving")

    if wo.get("related_return_id"):
        ret = store.returns.get(wo["related_return_id"])
        if ret and ret["status"] in ("REQUESTED", "ESCALATED"):
            raise_error(ERR_RELATED_RETURN_UNRESOLVED, "Linked return must be resolved first")

    data = request.get_json(force=True, silent=True) or {}
    resolution_notes = data.get("resolution_notes")

    wo["resolution_notes"] = resolution_notes
    wo["status"] = "RESOLVED"
    touch(wo)
    return success_response(serialize(wo))


@bp.route("/api/work-orders/<wo_id>/escalate", methods=["POST"])
def escalate_work_order(wo_id):
    check_role_permission({"CustomerService", "PlatformAdmin"})
    wo = store.work_orders.get(wo_id)
    if not wo:
        raise_error(ERR_NOT_FOUND, "Work order not found")

    if wo["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "Work order must be UNDER_REVIEW to escalate")

    wo["status"] = "ESCALATED"
    touch(wo)
    return success_response(serialize(wo))


@bp.route("/api/work-orders/<wo_id>/close", methods=["POST"])
def close_work_order(wo_id):
    check_role_permission({"CustomerService", "PlatformAdmin"})
    wo = store.work_orders.get(wo_id)
    if not wo:
        raise_error(ERR_NOT_FOUND, "Work order not found")

    if wo["status"] != "RESOLVED":
        raise_error(ERR_INVALID_STATE, "Work order must be RESOLVED to close")

    wo["status"] = "CLOSED"
    touch(wo)
    return success_response(serialize(wo))
