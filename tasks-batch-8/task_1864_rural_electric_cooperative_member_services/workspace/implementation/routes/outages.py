"""Outage Report endpoints."""
from flask import Blueprint, request

from middleware import get_context, require_roles, require_member_ownership, get_json_body
from response import ok, created, paginate
from errors import ApiError
from services import outage as outage_svc
from db import store

bp = Blueprint("outages", __name__)


@bp.route("/coop/outage-reports", methods=["POST"])
def create_outage_report():
    uid, role = get_context()
    require_roles(["Member", "Dispatcher", "MemberServicesRep"])
    body = get_json_body()
    result = outage_svc.create_outage_report(body, uid, role)
    return created(result)


@bp.route("/coop/outage-reports/<report_id>", methods=["GET"])
def get_outage_report(report_id):
    uid, role = get_context()
    require_roles(["Dispatcher", "FieldOpsCoordinator", "MemberServicesRep", "Member"])
    result = outage_svc.get_outage_report(report_id)
    if role == "Member":
        loc = store.service_locations.get(result["service_location_id"])
        if loc:
            require_member_ownership(loc.get("member_id"))
    return ok(result)


@bp.route("/coop/outage-reports", methods=["GET"])
def list_outage_reports():
    uid, role = get_context()
    require_roles(["Dispatcher", "FieldOpsCoordinator", "MemberServicesRep"])
    service_location_id = request.args.get("service_location_id")
    status = request.args.get("status")
    reported_by_member_id = request.args.get("reported_by_member_id")
    parent_outage_id = request.args.get("parent_outage_id")
    rows = outage_svc.list_outage_reports(service_location_id, status,
                                        reported_by_member_id, parent_outage_id)
    p = paginate()
    page = p(rows)
    return ok(page, rtype="array", pagination=p)


@bp.route("/coop/outage-reports/<report_id>/acknowledge", methods=["POST"])
def acknowledge_report(report_id):
    uid, role = get_context()
    require_roles(["Dispatcher"])
    result = outage_svc.acknowledge_report(report_id)
    return ok(result)


@bp.route("/coop/outage-reports/<report_id>/dispatch", methods=["POST"])
def dispatch_report(report_id):
    uid, role = get_context()
    require_roles(["Dispatcher"])
    result = outage_svc.dispatch_report(report_id)
    return ok(result)


@bp.route("/coop/outage-reports/<report_id>/restore", methods=["POST"])
def restore_report(report_id):
    uid, role = get_context()
    require_roles(["FieldOpsCoordinator"])
    result = outage_svc.restore_report(report_id)
    return ok(result)


@bp.route("/coop/outage-reports/<report_id>/mark-duplicate", methods=["POST"])
def mark_duplicate(report_id):
    uid, role = get_context()
    require_roles(["Dispatcher"])
    body = get_json_body()
    result = outage_svc.mark_duplicate(report_id, body)
    return ok(result)


@bp.route("/coop/outage-reports/<report_id>/cancel", methods=["POST"])
def cancel_report(report_id):
    uid, role = get_context()
    require_roles(["Dispatcher"])
    result = outage_svc.cancel_report(report_id)
    return ok(result)
