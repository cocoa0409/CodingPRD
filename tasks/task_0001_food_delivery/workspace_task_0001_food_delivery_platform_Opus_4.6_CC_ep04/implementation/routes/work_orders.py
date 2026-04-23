from flask import Blueprint, request
from middleware.auth import require_roles
from storage import db
from models.work_order import WorkOrder
from response import success_response
from errors import (raise_error, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_INVALID_STATE,
                    ERR_VALIDATION, ERR_RELATED_RETURN_UNRESOLVED)

bp = Blueprint("work_orders", __name__)

VALID_CATEGORIES = {
    "DELIVERY_LATE", "FOOD_QUALITY", "MISSING_ITEM", "RIDER_BEHAVIOR",
    "RESTAURANT_BEHAVIOR", "PAYMENT_ISSUE", "OTHER",
}
VALID_OPENER_ROLES = {"CUSTOMER", "RIDER", "RESTAURANT", "CUSTOMER_SERVICE"}


def get_work_order_or_404(wo_id):
    wo = db.work_orders.get(wo_id)
    if not wo:
        raise_error(ERR_NOT_FOUND, "Work order not found.")
    return wo


@bp.route("/api/work-orders", methods=["POST"])
@require_roles("Customer", "Rider", "Restaurant", "CustomerService", "PlatformAdmin")
def create_work_order():
    data = request.get_json(force=True, silent=True) or {}
    opened_by_role = data.get("opened_by_role")
    opened_by_id = data.get("opened_by_id")
    category = data.get("category")
    related_order_id = data.get("related_order_id")
    related_return_id = data.get("related_return_id")

    if opened_by_role not in VALID_OPENER_ROLES:
        raise_error(ERR_VALIDATION, "opened_by_role is required and must be valid.")
    if not opened_by_id:
        raise_error(ERR_VALIDATION, "opened_by_id is required.")
    if category not in VALID_CATEGORIES:
        raise_error(ERR_VALIDATION, "category must be a valid category.")

    if related_order_id:
        if not db.orders.get(related_order_id):
            raise_error(ERR_NOT_FOUND, "Related order not found.")
    if related_return_id:
        if not db.returns.get(related_return_id):
            raise_error(ERR_NOT_FOUND, "Related return not found.")

    wo = WorkOrder(opened_by_role, opened_by_id, category, related_order_id, related_return_id)
    db.work_orders[wo.id] = wo
    return success_response(wo.to_dict(), 201)


@bp.route("/api/work-orders/<wo_id>", methods=["GET"])
@require_roles("PlatformAdmin", "CustomerService", "Customer", "Rider", "Restaurant")
def get_work_order(wo_id):
    wo = get_work_order_or_404(wo_id)
    return success_response(wo.to_dict())


@bp.route("/api/work-orders/<wo_id>/assign", methods=["POST"])
@require_roles("CustomerService", "PlatformAdmin")
def assign_work_order(wo_id):
    wo = get_work_order_or_404(wo_id)
    if wo.status != "OPEN":
        raise_error(ERR_INVALID_STATE, "Work order must be in OPEN state to assign.")
    wo.assigned_cs_user_id = request.user_id
    wo.status = "UNDER_REVIEW"
    wo.touch()
    return success_response(wo.to_dict())


@bp.route("/api/work-orders/<wo_id>/request-info", methods=["POST"])
@require_roles("CustomerService", "PlatformAdmin")
def request_info(wo_id):
    wo = get_work_order_or_404(wo_id)
    if wo.status != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "Work order must be UNDER_REVIEW to request info.")
    wo.status = "AWAITING_INFO"
    wo.touch()
    return success_response(wo.to_dict())


@bp.route("/api/work-orders/<wo_id>/submit-info", methods=["POST"])
@require_roles("Customer", "Rider", "Restaurant")
def submit_info(wo_id):
    wo = get_work_order_or_404(wo_id)
    if wo.status != "AWAITING_INFO":
        raise_error(ERR_INVALID_STATE, "Work order must be AWAITING_INFO to submit info.")
    if request.user_id != wo.opened_by_id:
        raise_error(ERR_FORBIDDEN, "Only the opener can submit info.")
    wo.status = "UNDER_REVIEW"
    wo.touch()
    return success_response(wo.to_dict())


@bp.route("/api/work-orders/<wo_id>/resolve", methods=["POST"])
@require_roles("CustomerService", "PlatformAdmin")
def resolve_work_order(wo_id):
    wo = get_work_order_or_404(wo_id)
    if wo.status not in ("UNDER_REVIEW", "ESCALATED"):
        raise_error(ERR_INVALID_STATE, "Work order must be UNDER_REVIEW or ESCALATED to resolve.")
    if not wo.assigned_cs_user_id:
        raise_error(ERR_INVALID_STATE, "Work order must be assigned before resolving.")

    if wo.related_return_id:
        ret = db.returns.get(wo.related_return_id)
        if ret and ret.status in ("REQUESTED", "ESCALATED"):
            raise_error(ERR_RELATED_RETURN_UNRESOLVED, "Linked return must be resolved first.")

    data = request.get_json(force=True, silent=True) or {}
    resolution_notes = data.get("resolution_notes")
    wo.resolution_notes = resolution_notes
    wo.status = "RESOLVED"
    wo.touch()
    return success_response(wo.to_dict())


@bp.route("/api/work-orders/<wo_id>/escalate", methods=["POST"])
@require_roles("CustomerService", "PlatformAdmin")
def escalate_work_order(wo_id):
    wo = get_work_order_or_404(wo_id)
    if wo.status != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "Work order must be UNDER_REVIEW to escalate.")
    wo.status = "ESCALATED"
    wo.touch()
    return success_response(wo.to_dict())


@bp.route("/api/work-orders/<wo_id>/close", methods=["POST"])
@require_roles("CustomerService", "PlatformAdmin")
def close_work_order(wo_id):
    wo = get_work_order_or_404(wo_id)
    if wo.status != "RESOLVED":
        raise_error(ERR_INVALID_STATE, "Work order must be RESOLVED to close.")
    wo.status = "CLOSED"
    wo.touch()
    return success_response(wo.to_dict())
