"""AggregateDeal endpoints."""
from flask import Blueprint, request
from decimal import Decimal

from db import db
from middleware import require_roles
from response import success_object
from errors import err_invalid_request, err_invalid_state, err_referential
from services.core import (
    serialize_aggregate_deal, get_aggregate_deal, get_distributor, get_film,
    new_entity_common, touch,
)
from util import dec_pct
from ._helpers import get_json_body, require_fields, paginate_list

bp = Blueprint("aggregate_deals", __name__)


@bp.route("/distributors/<did>/aggregate-deals", methods=["POST"])
@require_roles("Booker")
def create_aggregate_deal(did, _user_id, _role):
    get_distributor(did)
    body = get_json_body()
    require_fields(body, ["film_id", "circuit", "aggregate_rental_pct", "min_screens",
                          "aggregate_house_allowance_cents"])
    # Referential check
    film = db.films.get(body["film_id"])
    if not film or film["distributor_id"] != did:
        raise err_referential("film_id not resolvable")
    pct = dec_pct(body["aggregate_rental_pct"])
    if pct is None:
        raise err_invalid_request("aggregate_rental_pct invalid")
    if not isinstance(body["min_screens"], int) or not isinstance(body["aggregate_house_allowance_cents"], int):
        raise err_invalid_request("min_screens and aggregate_house_allowance_cents must be integer")
    common = new_entity_common()
    a = {
        **common,
        "distributor_id": did,
        "film_id": body["film_id"],
        "circuit": body["circuit"],
        "deal_status": "DRAFT",
        "aggregate_rental_pct": pct,
        "min_screens": body["min_screens"],
        "aggregate_house_allowance_cents": body["aggregate_house_allowance_cents"],
    }
    db.aggregate_deals[a["id"]] = a
    return success_object(serialize_aggregate_deal(a), 201)


@bp.route("/distributors/<did>/aggregate-deals/<aid>", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "SettlementClerk", "Auditor")
def read_aggregate_deal(did, aid, _user_id, _role):
    return success_object(serialize_aggregate_deal(get_aggregate_deal(did, aid)))


@bp.route("/distributors/<did>/aggregate-deals", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "SettlementClerk", "Auditor")
def list_aggregate_deals(did, _user_id, _role):
    get_distributor(did)
    items = [a for a in db.aggregate_deals.values() if a["distributor_id"] == did]
    filters = {}
    for k in ("film_id", "circuit", "deal_status", "distributor_id"):
        if k in request.args:
            filters[k] = request.args.get(k)
    return paginate_list(items, serialize_aggregate_deal, filters)


@bp.route("/distributors/<did>/aggregate-deals/<aid>/activate", methods=["POST"])
@require_roles("Booker")
def activate_aggregate_deal(did, aid, _user_id, _role):
    a = get_aggregate_deal(did, aid)
    if a["deal_status"] != "DRAFT":
        raise err_invalid_state("AggregateDeal must be DRAFT to activate")
    # Count participating agreements in ACCEPTED/IN_PLAY
    participants = [b for b in db.booking_agreements.values()
                    if b.get("aggregate_deal_id") == aid
                    and b["deal_status"] in ("ACCEPTED", "IN_PLAY")]
    if len(participants) < a["min_screens"]:
        raise err_invalid_state("min_screens participating agreements required")
    a["deal_status"] = "ACTIVE"
    touch(a)
    return success_object(serialize_aggregate_deal(a))
