"""Cooperative endpoints."""
from flask import Blueprint, request

from middleware import get_context, require_roles, get_json_body
from response import ok, created, paginate
from errors import ApiError
from services import coop as coop_svc

bp = Blueprint("cooperatives", __name__)


@bp.route("/coop/cooperatives", methods=["POST"])
def create_cooperative():
    uid, role = get_context()
    require_roles(["PlatformAdmin"])
    body = get_json_body()
    result = coop_svc.create_cooperative(body)
    return created(result)


@bp.route("/coop/cooperatives/<coop_id>", methods=["GET"])
def get_cooperative(coop_id):
    uid, role = get_context()
    require_roles(["PlatformAdmin", "MemberServicesRep", "BoardDirector", "BoardSecretary",
                   "RateAnalyst", "BillingClerk", "FieldOpsCoordinator", "Dispatcher", "LegalCounsel"])
    result = coop_svc.get_cooperative(coop_id)
    return ok(result)


@bp.route("/coop/cooperatives", methods=["GET"])
def list_cooperatives():
    uid, role = get_context()
    require_roles(["PlatformAdmin", "MemberServicesRep", "BoardDirector", "BoardSecretary"])
    active_election_id = request.args.get("active_election_id")
    rows = coop_svc.list_cooperatives(active_election_id)
    p = paginate()
    page = p(rows)
    return ok(page, rtype="array", pagination=p)


@bp.route("/coop/cooperatives/<coop_id>/post-margin", methods=["POST"])
def post_margin(coop_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep"])
    body = get_json_body()
    result = coop_svc.post_margin(coop_id, body)
    return ok(result)
