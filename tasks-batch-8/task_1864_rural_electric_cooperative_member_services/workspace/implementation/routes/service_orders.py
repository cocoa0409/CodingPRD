"""ServiceOrder endpoints."""
from flask import Blueprint, request

from middleware import get_context, require_roles, require_member_ownership, get_json_body
from response import ok, created, paginate
from errors import ApiError
from services import service_order as so_svc
from db import store

bp = Blueprint("service_orders", __name__)


@bp.route("/coop/service-orders", methods=["POST"])
def create_service_order():
    uid, role = get_context()
    require_roles(["MemberServicesRep"])
    body = get_json_body()
    result = so_svc.create_service_order(body)
    return created(result)


@bp.route("/coop/service-orders/<order_id>", methods=["GET"])
def get_service_order(order_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep", "FieldOpsCoordinator", "Member"])
    result = so_svc.get_service_order(order_id)
    if role == "Member":
        loc = store.service_locations.get(result["service_location_id"])
        if loc:
            require_member_ownership(loc.get("member_id"))
    return ok(result)


@bp.route("/coop/service-orders", methods=["GET"])
def list_service_orders():
    uid, role = get_context()
    require_roles(["MemberServicesRep", "FieldOpsCoordinator"])
    service_location_id = request.args.get("service_location_id")
    status = request.args.get("status")
    row_agreement_id = request.args.get("row_agreement_id")
    rows = so_svc.list_service_orders(service_location_id, status, row_agreement_id)
    p = paginate()
    page = p(rows)
    return ok(page, rtype="array", pagination=p)


@bp.route("/coop/service-orders/<order_id>/estimate", methods=["POST"])
def estimate_order(order_id):
    uid, role = get_context()
    require_roles(["FieldOpsCoordinator"])
    result = so_svc.estimate_order(order_id)
    return ok(result)


@bp.route("/coop/service-orders/<order_id>/invoice-atc", methods=["POST"])
def invoice_atc(order_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep"])
    result = so_svc.invoice_atc(order_id)
    return ok(result)


@bp.route("/coop/service-orders/<order_id>/mark-paid", methods=["POST"])
def mark_paid(order_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep"])
    result = so_svc.mark_paid(order_id)
    return ok(result)


@bp.route("/coop/service-orders/<order_id>/schedule", methods=["POST"])
def schedule_order(order_id):
    uid, role = get_context()
    require_roles(["FieldOpsCoordinator"])
    result = so_svc.schedule_order(order_id)
    return ok(result)


@bp.route("/coop/service-orders/<order_id>/construct", methods=["POST"])
def construct_order(order_id):
    uid, role = get_context()
    require_roles(["FieldOpsCoordinator"])
    result = so_svc.construct_order(order_id)
    return ok(result)


@bp.route("/coop/service-orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    uid, role = get_context()
    require_roles(["FieldOpsCoordinator"])
    result = so_svc.cancel_order(order_id)
    return ok(result)
