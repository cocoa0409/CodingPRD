"""Market endpoints."""
from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import success_object
from errors import err_invalid_request
from services.core import (
    serialize_market, get_market, get_distributor, new_entity_common,
)
from ._helpers import get_json_body, require_fields, paginate_list

bp = Blueprint("markets", __name__)


TIERS = {"TIER_1", "TIER_2", "TIER_3"}


@bp.route("/distributors/<did>/markets", methods=["POST"])
@require_roles("PlatformAdmin")
def create_market(did, _user_id, _role):
    get_distributor(did)
    body = get_json_body()
    require_fields(body, ["code", "population_tier", "weekly_coop_budget_cents"])
    if body["population_tier"] not in TIERS:
        raise err_invalid_request("population_tier must be TIER_1|TIER_2|TIER_3")
    if not isinstance(body["weekly_coop_budget_cents"], int):
        raise err_invalid_request("weekly_coop_budget_cents must be integer")
    common = new_entity_common()
    m = {
        **common,
        "distributor_id": did,
        "code": body["code"],
        "population_tier": body["population_tier"],
        "weekly_coop_budget_cents": body["weekly_coop_budget_cents"],
    }
    db.markets[m["id"]] = m
    return success_object(serialize_market(m), 201)


@bp.route("/distributors/<did>/markets/<mid>", methods=["GET"])
@require_roles("Any")
def read_market(did, mid, _user_id, _role):
    return success_object(serialize_market(get_market(did, mid)))


@bp.route("/distributors/<did>/markets", methods=["GET"])
@require_roles("Any")
def list_markets(did, _user_id, _role):
    get_distributor(did)
    items = [m for m in db.markets.values() if m["distributor_id"] == did]
    filters = {}
    if "distributor_id" in request.args:
        filters["distributor_id"] = request.args.get("distributor_id")
    return paginate_list(items, serialize_market, filters)
