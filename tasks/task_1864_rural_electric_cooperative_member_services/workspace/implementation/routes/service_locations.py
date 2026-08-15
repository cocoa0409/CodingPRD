"""ServiceLocation endpoints."""
from flask import Blueprint

from middleware import get_context, require_roles, require_member_ownership, get_json_body
from response import ok, created
from errors import ApiError
from services import service_location as loc_svc
from db import store

bp = Blueprint("service_locations", __name__)


@bp.route("/coop/service-locations", methods=["POST"])
def create_service_location():
    uid, role = get_context()
    require_roles(["MemberServicesRep"])
    body = get_json_body()
    result = loc_svc.create_service_location(body)
    return created(result)


@bp.route("/coop/service-locations/<loc_id>", methods=["GET"])
def get_service_location(loc_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep", "BillingClerk", "FieldOpsCoordinator", "Dispatcher", "Member"])
    result = loc_svc.get_service_location(loc_id)
    if role == "Member":
        require_member_ownership(result.get("member_id"))
    return ok(result)


@bp.route("/coop/service-locations/<loc_id>/energize", methods=["POST"])
def energize_location(loc_id):
    uid, role = get_context()
    require_roles(["FieldOpsCoordinator"])
    result = loc_svc.energize_location(loc_id)
    return ok(result)


@bp.route("/coop/service-locations/<loc_id>/disconnect", methods=["POST"])
def disconnect_location(loc_id):
    uid, role = get_context()
    require_roles(["FieldOpsCoordinator"])
    result = loc_svc.disconnect_location(loc_id)
    return ok(result)


@bp.route("/coop/service-locations/<loc_id>/remove", methods=["POST"])
def remove_location(loc_id):
    uid, role = get_context()
    require_roles(["FieldOpsCoordinator"])
    result = loc_svc.remove_location(loc_id)
    return ok(result)
