"""Member endpoints."""
from flask import Blueprint, request

from middleware import get_context, require_roles, require_member_ownership, get_json_body
from response import ok, created, paginate
from errors import ApiError
from services import member as member_svc
from services import capital_credit as cc_svc
from db import store

bp = Blueprint("members", __name__)


@bp.route("/coop/members", methods=["POST"])
def create_member():
    uid, role = get_context()
    require_roles(["MemberServicesRep"])
    body = get_json_body()
    result = member_svc.create_member(body)
    return created(result)


@bp.route("/coop/members/<member_id>", methods=["GET"])
def get_member(member_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep", "BoardDirector", "BoardSecretary", "BillingClerk", "Member"])
    result = member_svc.get_member(member_id)
    if role == "Member":
        require_member_ownership(result["id"])
    return ok(result)


@bp.route("/coop/members", methods=["GET"])
def list_members():
    uid, role = get_context()
    require_roles(["MemberServicesRep", "BoardDirector", "BoardSecretary", "BillingClerk"])
    status = request.args.get("status")
    district_id = request.args.get("district_id")
    rows = member_svc.list_members(status, district_id)
    p = paginate()
    page = p(rows)
    return ok(page, rtype="array", pagination=p)


@bp.route("/coop/members/<member_id>/activate", methods=["POST"])
def activate_member(member_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep"])
    result = member_svc.activate_member(member_id)
    return ok(result)


@bp.route("/coop/members/<member_id>/suspend", methods=["POST"])
def suspend_member(member_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep"])
    result = member_svc.suspend_member(member_id)
    return ok(result)


@bp.route("/coop/members/<member_id>/reinstate", methods=["POST"])
def reinstate_member(member_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep"])
    result = member_svc.reinstate_member(member_id)
    return ok(result)


@bp.route("/coop/members/<member_id>/terminate", methods=["POST"])
def terminate_member(member_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep"])
    result = member_svc.terminate_member(member_id)
    return ok(result)


@bp.route("/coop/members/<member_id>/service-locations", methods=["GET"])
def list_member_locations(member_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep", "BillingClerk", "FieldOpsCoordinator", "Member"])
    # Verify member exists
    member_svc.get_member(member_id)
    if role == "Member":
        require_member_ownership(member_id)
    rows = [sl for sl in store.service_locations.values() if sl.get("member_id") == member_id]
    p = paginate()
    page = p(rows)
    return ok(page, rtype="array", pagination=p)


@bp.route("/coop/members/<member_id>/capital-credit-payouts", methods=["GET"])
def list_member_payouts(member_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep", "BoardDirector", "Member"])
    # Verify member exists
    member_svc.get_member(member_id)
    if role == "Member":
        require_member_ownership(member_id)
    rows = cc_svc.get_member_payouts(member_id)
    p = paginate()
    page = p(rows)
    return ok(page, rtype="array", pagination=p)
