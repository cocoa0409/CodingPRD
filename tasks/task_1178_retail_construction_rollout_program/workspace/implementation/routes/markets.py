"""Market endpoints (§3.1)."""
from flask import Blueprint

from db import store
from errors import ApiError
from middleware import ALL_ROLES, authed
from response import ok
from routes import list_response, require_state
from util import bump, new_entity, serialize
from validate import body_fk, get_or_404, json_body, req_int, req_str

bp = Blueprint("markets", __name__)

TERMINAL = ("AWARDED",)


@bp.route("/rollout/markets", methods=["POST"], strict_slashes=False)
@authed(["ProgramDirector"])
def create_market():
    body = json_body()
    program = body_fk(body, "program_id", store.programs)
    name = req_str(body, "name")
    state_code = req_str(body, "state_code")
    max_crews = req_int(body, "max_concurrent_vendor_crews")
    if program is None:
        from errors import invalid_request
        invalid_request("field 'program_id' is required")
    market = new_entity(store)
    market.update({
        "program_id": program["id"],
        "name": name,
        "state_code": state_code,
        "max_concurrent_vendor_crews": max_crews,
        "status": "REGISTERED",
    })
    store.markets[market["id"]] = market
    return ok(serialize(market), status=201)


@bp.route("/rollout/markets", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def list_markets():
    return list_response(store.markets, [
        ("program_id", "program_id", "str"),
        ("status", "status", "str"),
    ])


@bp.route("/rollout/markets/<marketId>", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def get_market(marketId):
    return ok(serialize(get_or_404(store.markets, marketId, "market")))


@bp.route("/rollout/markets/<marketId>/open-bidding", methods=["POST"], strict_slashes=False)
@authed(["ProcurementLead"])
def open_bidding(marketId):
    market = get_or_404(store.markets, marketId, "market")
    require_state(market, ("REGISTERED",), TERMINAL)
    program = store.programs.get(market["program_id"])
    if program is None or program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409,
                       "parent program is not ACTIVE")
    market["status"] = "BIDDING"
    bump(market)
    return ok(serialize(market))
