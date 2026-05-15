"""WorkOrder routes (§3.6)."""

from flask import Blueprint, g

import response as resp
from middleware import require_roles
from services import work_order_service
from services.common import serialize


bp = Blueprint("work_orders", __name__)


@bp.route("/work-orders", methods=["POST"])
def create_wo():
    require_roles("Exhibitor")
    row = work_order_service.create_work_order(g.body)
    return resp.created(serialize(row))


@bp.route("/work-orders/<wo_id>/submit", methods=["POST"])
def submit_wo(wo_id):
    require_roles("Exhibitor")
    row = work_order_service.submit_work_order(wo_id, g.body)
    return resp.success(serialize(row))


@bp.route("/work-orders/<wo_id>/dispatch", methods=["POST"])
def dispatch_wo(wo_id):
    require_roles("VenueOps")
    row = work_order_service.dispatch_work_order(wo_id, g.body)
    return resp.success(serialize(row))


@bp.route("/work-orders/<wo_id>/confirm-execution", methods=["POST"])
def confirm_wo(wo_id):
    require_roles("ServiceProvider")
    row = work_order_service.confirm_execution(wo_id, g.body)
    return resp.success(serialize(row))


@bp.route("/work-orders/<wo_id>/bill", methods=["POST"])
def bill_wo(wo_id):
    require_roles("VenueOps")
    row = work_order_service.bill_work_order(wo_id, g.body)
    return resp.success(serialize(row))


@bp.route("/work-orders/<wo_id>/dispute", methods=["POST"])
def dispute_wo(wo_id):
    require_roles("Exhibitor")
    row = work_order_service.dispute_work_order(wo_id, g.body)
    return resp.success(serialize(row))


@bp.route("/work-orders/<wo_id>/resolve", methods=["POST"])
def resolve_wo(wo_id):
    require_roles("VenueOps")
    row = work_order_service.resolve_work_order(wo_id, g.body)
    return resp.success(serialize(row))


@bp.route("/work-orders/<wo_id>/cancel", methods=["POST"])
def cancel_wo(wo_id):
    require_roles("Exhibitor")
    row = work_order_service.cancel_work_order(wo_id, g.body)
    return resp.success(serialize(row))
