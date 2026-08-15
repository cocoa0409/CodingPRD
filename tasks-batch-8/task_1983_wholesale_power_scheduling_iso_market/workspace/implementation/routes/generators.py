from decimal import Decimal

from flask import Blueprint

from auth import parse_auth, require_role, check_ownership, ALL_ROLES
from db import store
from envelope import ok, paginate
from errors import not_found, conflict, ERR_INVALID_STATE, ERR_OPEN_COMMITMENTS
from util import (get_body, check_unknown, req_string, req_number, new_record,
                  serialize, sort_key, touch)

bp = Blueprint("generators", __name__)


def get_generator(gid):
    g = store.generators.get(gid)
    if g is None:
        raise not_found("generator not found")
    return g


@bp.post("/market/generators")
def create_generator():
    auth = parse_auth()
    require_role(auth, ["IsoOperator"])
    body = get_body()
    check_unknown(body, {"market_participant_id", "unit_name", "pricing_node", "capacity_mw"})
    pid = req_string(body, "market_participant_id")
    unit_name = req_string(body, "unit_name")
    pricing_node = req_string(body, "pricing_node")
    capacity = req_number(body, "capacity_mw", minimum=Decimal(0), min_exclusive=True)
    if pid not in store.participants:
        raise not_found("market participant not found")
    rec = new_record()
    rec.update({
        "market_participant_id": pid,
        "unit_name": unit_name,
        "pricing_node": pricing_node,
        "capacity_mw": capacity,
        "availability_mw": capacity,
        "status": "AVAILABLE",
    })
    store.generators[rec["id"]] = rec
    return ok(serialize(rec), status=201)


@bp.get("/market/generators/<generatorId>")
def get_one(generatorId):
    parse_auth()
    return ok(serialize(get_generator(generatorId)))


@bp.get("/market/generators")
def list_generators():
    parse_auth()
    rows = sorted(store.generators.values(), key=sort_key)
    pid = None
    status = None
    from flask import request
    pid = request.args.get("market_participant_id")
    status = request.args.get("status")
    if pid is not None:
        rows = [r for r in rows if r["market_participant_id"] == pid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate([serialize(r) for r in rows])


@bp.post("/market/generators/<generatorId>/decommission")
def decommission(generatorId):
    auth = parse_auth()
    require_role(auth, ["Trader"])
    gen = get_generator(generatorId)
    check_ownership(auth, gen["market_participant_id"])
    if gen["status"] != "AVAILABLE":
        raise conflict(ERR_INVALID_STATE,
                       "generator must be AVAILABLE to decommission")
    open_offers = any(o["generator_asset_id"] == gen["id"]
                      and o["status"] in ("DRAFT", "SUBMITTED")
                      for o in store.offers.values())
    open_outages = any(o["generator_asset_id"] == gen["id"]
                       and o["status"] in ("SUBMITTED", "ACKNOWLEDGED", "APPROVED")
                       for o in store.outages.values())
    open_obligations = any(o["generator_asset_id"] == gen["id"]
                           and o["status"] in ("ACTIVE", "AT_RISK")
                           for o in store.obligations.values())
    if open_offers or open_outages or open_obligations:
        raise conflict(ERR_OPEN_COMMITMENTS,
                       "generator has open offers, outages, or obligations")
    gen["status"] = "DECOMMISSIONED"
    touch(gen)
    return ok(serialize(gen))
