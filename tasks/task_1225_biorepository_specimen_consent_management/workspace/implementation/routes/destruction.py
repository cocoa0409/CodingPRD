"""Destruction order endpoints."""
from flask import Blueprint, request

import db
from errors import raise_error
from middleware import (
    require_roles,
    get_json_body,
    check_known_fields,
    require_fields,
    validate_enum,
    validate_string,
    parse_pagination,
    ALL_ROLES,
)
from response import success_object, success_list
from serializers import destruction_order_out
from services.common import get_or_404
from services.destruction import create_destruction_order, execute_destruction

bp = Blueprint("destruction", __name__)

REASONS = {"CONSENT_WITHDRAWAL", "QUALITY_FAILURE", "OTHER"}


@bp.route("/biobank/destruction-orders", methods=["POST"])
def create_order():
    user_id, _ = require_roles({"QualityOfficer"})
    body = get_json_body()
    check_known_fields(body, {"specimen_id", "reason"})
    require_fields(body, ["specimen_id", "reason"])
    specimen_id = validate_string(body["specimen_id"], "specimen_id")
    reason = validate_enum(body["reason"], REASONS, "reason")
    specimen = db.specimens.get(specimen_id)
    if specimen is None:
        raise_error("ERR_NOT_FOUND", f"specimen not found: {specimen_id}")
    order = create_destruction_order(specimen_id, reason, user_id, consent_record_id=None)
    return success_object(destruction_order_out(order), status=201)


@bp.route("/biobank/destruction-orders", methods=["GET"])
def list_orders():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.destruction_orders.values())
    consent_record_id = request.args.get("consent_record_id")
    specimen_id = request.args.get("specimen_id")
    status = request.args.get("status")
    if consent_record_id is not None:
        items = [o for o in items if o["consent_record_id"] == consent_record_id]
    if specimen_id is not None:
        items = [o for o in items if o["specimen_id"] == specimen_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items.sort(key=lambda o: o["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([destruction_order_out(o) for o in page], limit, offset, total)


@bp.route("/biobank/destruction-orders/<orderId>", methods=["GET"])
def get_order(orderId):
    require_roles(ALL_ROLES)
    order = get_or_404(db.destruction_orders, orderId, "destruction order")
    return success_object(destruction_order_out(order))


@bp.route("/biobank/destruction-orders/<orderId>/confirm-execution", methods=["POST"])
def confirm_execution(orderId):
    user_id, _ = require_roles({"QualityOfficer"})
    order = get_or_404(db.destruction_orders, orderId, "destruction order")
    get_json_body()
    # State check precedes the segregation check.
    if order["status"] != "PENDING":
        raise_error("ERR_DESTRUCTION_ORDER_NOT_CONFIRMABLE", "Order is not PENDING")
    if order["created_by_user_id"] == user_id:
        raise_error("ERR_SEGREGATION_OF_DUTIES", "Confirmer must differ from creator")
    execute_destruction(order, user_id)
    return success_object(destruction_order_out(order))
