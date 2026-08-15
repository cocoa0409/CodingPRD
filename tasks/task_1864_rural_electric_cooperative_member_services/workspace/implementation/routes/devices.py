"""LoadManagementDevice endpoints."""
from flask import Blueprint, request

from middleware import get_context, require_roles, require_member_ownership, get_json_body
from response import ok, created, paginate
from errors import ApiError
from services import device as dev_svc
from db import store

bp = Blueprint("devices", __name__)


@bp.route("/coop/load-management-devices", methods=["POST"])
def create_device():
    uid, role = get_context()
    require_roles(["Member", "MemberServicesRep"])
    body = get_json_body()
    result = dev_svc.create_device(body, uid, role)
    return created(result)


@bp.route("/coop/load-management-devices/<dev_id>", methods=["GET"])
def get_device(dev_id):
    uid, role = get_context()
    require_roles(["FieldOpsCoordinator", "MemberServicesRep", "Member"])
    result = dev_svc.get_device(dev_id)
    if role == "Member":
        loc = store.service_locations.get(result["service_location_id"])
        if loc:
            require_member_ownership(loc.get("member_id"))
    return ok(result)


@bp.route("/coop/load-management-devices", methods=["GET"])
def list_devices():
    uid, role = get_context()
    require_roles(["FieldOpsCoordinator", "MemberServicesRep"])
    service_location_id = request.args.get("service_location_id")
    status = request.args.get("status")
    rows = dev_svc.list_devices(service_location_id, status)
    p = paginate()
    page = p(rows)
    return ok(page, rtype="array", pagination=p)


@bp.route("/coop/load-management-devices/<dev_id>/activate", methods=["POST"])
def activate_device(dev_id):
    uid, role = get_context()
    require_roles(["FieldOpsCoordinator"])
    result = dev_svc.activate_device(dev_id)
    return ok(result)


@bp.route("/coop/load-management-devices/<dev_id>/suspend", methods=["POST"])
def suspend_device(dev_id):
    uid, role = get_context()
    require_roles(["FieldOpsCoordinator"])
    result = dev_svc.suspend_device(dev_id)
    return ok(result)


@bp.route("/coop/load-management-devices/<dev_id>/reactivate", methods=["POST"])
def reactivate_device(dev_id):
    uid, role = get_context()
    require_roles(["FieldOpsCoordinator"])
    result = dev_svc.reactivate_device(dev_id)
    return ok(result)


@bp.route("/coop/load-management-devices/<dev_id>/unenroll", methods=["POST"])
def unenroll_device(dev_id):
    uid, role = get_context()
    require_roles(["Member"])
    result = dev_svc.unenroll_device(dev_id, uid)
    return ok(result)
