"""CastContract endpoints."""
from decimal import Decimal

from flask import Blueprint

from db import store, new_id, next_seq
from errors import (
    ERR_CONTRACT_NOT_FOUND,
    ERR_SEASON_NOT_FOUND,
    ERR_PERFORMER_NOT_FOUND,
    ERR_SEASON_INVALID_STATE,
    ERR_CONTRACT_NOT_OFFERABLE,
    ERR_CONTRACT_NOT_OFFERED,
    ERR_CONTRACT_NOT_TERMINABLE,
    conflict,
)
from middleware import (
    require_roles,
    require_owner,
    get_body,
    load,
    parse_pagination,
    apply_filters,
    sorted_by_creation,
)
from response import obj_response, list_response
from services import terminate_contract_cascade, CONTRACT_TERMINAL
from util import req, opt, present, check_unknown, new_record, mutate, public_view

bp = Blueprint("cast_contracts", __name__)

CREATE_FIELDS = {
    "season_id",
    "performer_id",
    "offered_day_rate_cents",
    "guaranteed_days",
    "weather_pay_pct",
    "required_rehearsal_hours",
}


def load_contract(cid):
    return load(store.contracts, cid, ERR_CONTRACT_NOT_FOUND, "cast contract")


@bp.route("/cast-contracts", methods=["POST"])
def create_contract():
    require_roles("CastDirector")
    body = get_body()
    # Layer 3 body FK existence in canonical order: season_id, then performer_id.
    if isinstance(body.get("season_id"), str):
        load(store.seasons, body["season_id"], ERR_SEASON_NOT_FOUND, "season")
    if isinstance(body.get("performer_id"), str):
        load(store.performers, body["performer_id"], ERR_PERFORMER_NOT_FOUND, "performer")
    check_unknown(body, CREATE_FIELDS)
    season_id = req(body, "season_id", "str")
    performer_id = req(body, "performer_id", "str")
    offered = req(body, "offered_day_rate_cents", "int", lo=0)
    guaranteed_days = req(body, "guaranteed_days", "int", lo=0)
    weather_pay_pct = req(body, "weather_pay_pct", "num", lo=0, hi=1)
    required_rehearsal_hours = req(body, "required_rehearsal_hours", "num", lo=0)

    season = store.seasons[season_id]
    if season["status"] not in ("PLANNING", "BUILD"):
        raise conflict(
            ERR_SEASON_INVALID_STATE, "contract creation requires season PLANNING or BUILD"
        )
    contract = new_record()
    contract.update(
        {
            "id": new_id(),
            "_seq": next_seq(),
            "season_id": season_id,
            "performer_id": performer_id,
            "status": "DRAFT",
            "offered_day_rate_cents": offered,
            "countered_day_rate_cents": None,
            "guaranteed_days": guaranteed_days,
            "weather_pay_pct": weather_pay_pct,
            "required_rehearsal_hours": required_rehearsal_hours,
            "completed_rehearsal_hours": Decimal(0),
            "negotiation_round": 0,
            "accrued_payout_cents": 0,
            "final_payout_cents": None,
        }
    )
    store.contracts[contract["id"]] = contract
    return obj_response(public_view(contract), 201)


@bp.route("/cast-contracts", methods=["GET"])
def list_contracts():
    require_roles()
    limit, offset = parse_pagination()
    items = apply_filters(
        sorted_by_creation(store.contracts),
        [("season_id", "season_id"), ("performer_id", "performer_id"), ("status", "status")],
    )
    total = len(items)
    page = items[offset : offset + limit]
    return list_response([public_view(c) for c in page], limit, offset, total)


@bp.route("/cast-contracts/<cid>", methods=["GET"])
def get_contract(cid):
    require_roles()
    return obj_response(public_view(load_contract(cid)))


@bp.route("/cast-contracts/<cid>/offer", methods=["POST"])
def offer_contract(cid):
    require_roles("CastDirector")
    contract = load_contract(cid)
    body = get_body()
    check_unknown(body, {"offered_day_rate_cents"})
    rate = opt(body, "offered_day_rate_cents", "int", lo=0)
    if contract["status"] not in ("DRAFT", "COUNTERED"):
        raise conflict(ERR_CONTRACT_NOT_OFFERABLE, "offer requires DRAFT or COUNTERED")
    season = store.seasons[contract["season_id"]]
    if season["status"] not in ("PLANNING", "BUILD"):
        raise conflict(ERR_SEASON_INVALID_STATE, "offer requires season PLANNING or BUILD")
    changes = {"status": "OFFERED", "negotiation_round": contract["negotiation_round"] + 1}
    if present(body, "offered_day_rate_cents"):
        changes["offered_day_rate_cents"] = rate
    elif contract["status"] == "COUNTERED":
        # Re-offer from COUNTERED with omitted rate adopts the countered rate.
        changes["offered_day_rate_cents"] = contract["countered_day_rate_cents"]
    mutate(contract, **changes)
    return obj_response(public_view(contract))


@bp.route("/cast-contracts/<cid>/counter", methods=["POST"])
def counter_contract(cid):
    uid, _ = require_roles("Performer")
    contract = load_contract(cid)
    require_owner(uid == contract["performer_id"])
    body = get_body()
    check_unknown(body, {"countered_day_rate_cents"})
    rate = req(body, "countered_day_rate_cents", "int", lo=0)
    if contract["status"] != "OFFERED":
        raise conflict(ERR_CONTRACT_NOT_OFFERED, "counter requires OFFERED")
    mutate(
        contract,
        status="COUNTERED",
        countered_day_rate_cents=rate,
        negotiation_round=contract["negotiation_round"] + 1,
    )
    return obj_response(public_view(contract))


@bp.route("/cast-contracts/<cid>/accept", methods=["POST"])
def accept_contract(cid):
    uid, _ = require_roles("Performer")
    contract = load_contract(cid)
    require_owner(uid == contract["performer_id"])
    check_unknown(get_body(), set())
    if contract["status"] != "OFFERED":
        raise conflict(ERR_CONTRACT_NOT_OFFERED, "accept requires OFFERED")
    mutate(contract, status="ACCEPTED")
    return obj_response(public_view(contract))


@bp.route("/cast-contracts/<cid>/terminate", methods=["POST"])
def terminate_contract(cid):
    require_roles("CastDirector")
    contract = load_contract(cid)
    check_unknown(get_body(), set())
    if contract["status"] in CONTRACT_TERMINAL:
        raise conflict(ERR_CONTRACT_NOT_TERMINABLE, "terminate requires a non-terminal contract")
    terminate_contract_cascade(contract)
    return obj_response(public_view(contract))
