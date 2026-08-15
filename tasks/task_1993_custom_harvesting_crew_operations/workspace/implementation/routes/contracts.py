"""CustomerContract endpoints (§3.2)."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_CONTRACT_NOT_FOUND,
    ERR_CONTRACT_NOT_DRAFT,
    ERR_CONTRACT_NOT_CANCELLABLE,
    ERR_SEASON_NOT_OPEN_FOR_COMMIT,
    ERR_INVALID_REQUEST,
)
from helpers import (
    get_json_body,
    require_fields,
    require_type,
    require_enum,
    is_number,
    stamp_new,
    touch,
    public,
    sort_key,
    get_season_or_404,
    get_contract_or_404,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination, paginate
from services.domain import (
    recompute_season_committed_acres,
    skip_stop_cascade,
)

bp = Blueprint("contracts", __name__)

CROPS = ("WHEAT", "CORN", "SOYBEAN", "SORGHUM")
RATE_BASES = ("PER_ACRE", "PER_BUSHEL")


@bp.route("/harvest/seasons/<seasonId>/contracts", methods=["POST"])
def create_contract(seasonId):
    require_roles("GrowerLiaison")
    season = get_season_or_404(seasonId)
    body = get_json_body()
    require_fields(
        body,
        [
            "grower_name",
            "state_code",
            "crop",
            "rate_basis",
            "rate_cents_per_acre",
            "rate_cents_per_bushel",
            "committed_acres",
        ],
    )
    grower_name = require_type(body, "grower_name", "string")
    state_code = require_type(body, "state_code", "string")
    crop = require_enum(body, "crop", CROPS)
    rate_basis = require_enum(body, "rate_basis", RATE_BASES)
    rate_cents_per_acre = require_type(body, "rate_cents_per_acre", "int")
    rate_cents_per_bushel = require_type(body, "rate_cents_per_bushel", "int")
    committed_acres = require_type(body, "committed_acres", "number")

    record = stamp_new(
        {
            "season_id": season["id"],
            "grower_name": grower_name,
            "state_code": state_code,
            "crop": crop,
            "rate_basis": rate_basis,
            "rate_cents_per_acre": rate_cents_per_acre,
            "rate_cents_per_bushel": rate_cents_per_bushel,
            "committed_acres": committed_acres,
            "harvested_acres": 0,
            "moisture_discount_total_cents": 0,
            "status": "DRAFT",
        }
    )
    db.contracts[record["id"]] = record
    return success_object(public(record), status=201)


@bp.route("/harvest/contracts", methods=["GET"])
def list_contracts():
    require_roles(*ALL_ROLES)
    pagination = parse_pagination(request.args)
    season_id = request.args.get("season_id")
    status = request.args.get("status")
    items = list(db.contracts.values())
    if season_id is not None:
        items = [c for c in items if c["season_id"] == season_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=sort_key)
    page, pag = paginate(items, pagination)
    return success_list([public(r) for r in page], pag)


@bp.route("/harvest/seasons/<seasonId>/contracts", methods=["GET"])
def list_contracts_under_season(seasonId):
    require_roles(*ALL_ROLES)
    season = get_season_or_404(seasonId)
    pagination = parse_pagination(request.args)
    items = [c for c in db.contracts.values() if c["season_id"] == season["id"]]
    items.sort(key=sort_key)
    page, pag = paginate(items, pagination)
    return success_list([public(r) for r in page], pag)


@bp.route("/harvest/contracts/<contractId>", methods=["GET"])
def get_contract(contractId):
    require_roles(*ALL_ROLES)
    contract = get_contract_or_404(contractId)
    return success_object(public(contract))


@bp.route("/harvest/contracts/<contractId>/commit", methods=["POST"])
def commit_contract(contractId):
    require_roles("GrowerLiaison")
    contract = get_contract_or_404(contractId)
    if contract["status"] != "DRAFT":
        raise ApiError(ERR_CONTRACT_NOT_DRAFT, 409, "commit requires contract DRAFT")
    season = get_season_or_404(contract["season_id"])
    if season["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(
            ERR_SEASON_NOT_OPEN_FOR_COMMIT,
            409,
            "commit requires season DRAFT or ACTIVE",
        )
    if not is_number(contract.get("committed_acres")) or contract["committed_acres"] <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "committed_acres must be > 0")
    contract["status"] = "COMMITTED"
    touch(contract)
    recompute_season_committed_acres(season)
    return success_object(public(contract))


@bp.route("/harvest/contracts/<contractId>/cancel", methods=["POST"])
def cancel_contract(contractId):
    require_roles("GrowerLiaison")
    contract = get_contract_or_404(contractId)
    if contract["status"] not in ("DRAFT", "COMMITTED"):
        raise ApiError(
            ERR_CONTRACT_NOT_CANCELLABLE,
            409,
            "cancel requires contract DRAFT or COMMITTED",
        )
    # Cascade: every SCHEDULED stop of this contract → SKIPPED; RESERVED
    # assignments → CANCELLED; machines released if unallocated.
    for s in list(db.route_stops.values()):
        if s["contract_id"] == contract["id"] and s["status"] == "SCHEDULED":
            skip_stop_cascade(s)
    contract["status"] = "CANCELLED"
    touch(contract)
    season = get_season_or_404(contract["season_id"])
    recompute_season_committed_acres(season)
    return success_object(public(contract))
