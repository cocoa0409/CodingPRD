"""Settlement endpoints (§3.8)."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_SETTLEMENT_NOT_DRAFT,
    ERR_SETTLEMENT_NOT_ISSUED,
    ERR_SETTLEMENT_NOT_DISPUTED,
    ERR_CONTRACT_NOT_HARVESTED,
    ERR_SEASON_NOT_SETTLING,
    ERR_STALE_VERSION,
)
from helpers import (
    get_json_body,
    require_fields,
    require_type,
    is_int,
    stamp_new,
    touch,
    public,
    sort_key,
    get_contract_or_404,
    get_settlement_or_404,
    get_season_or_404,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination, paginate
from services.calculations import (
    settlement_base_amount,
    fuel_surcharge_cents,
    moisture_discount_cents,
    settlement_total,
)

bp = Blueprint("settlements", __name__)


def _contract_tickets(contract_id):
    """All delivery tickets for the contract (append-only, no status filter)."""
    return [t for t in db.delivery_tickets.values() if t["contract_id"] == contract_id]


def _settle_contract(contract):
    """Auto-transition HARVESTED → SETTLED on PAID / RESOLVED."""
    if contract["status"] == "HARVESTED":
        contract["status"] = "SETTLED"
        touch(contract)


@bp.route("/harvest/contracts/<contractId>/settlements", methods=["POST"])
def create_settlement(contractId):
    require_roles("BillingClerk")
    contract = get_contract_or_404(contractId)
    record = stamp_new(
        {
            "contract_id": contract["id"],
            "season_id": contract["season_id"],
            "base_amount_cents": 0,
            "fuel_surcharge_cents": 0,
            "hauling_add_on_total_cents": 0,
            "moisture_discount_cents": 0,
            "total_amount_cents": 0,
            "issued_at": None,
            "status": "DRAFT",
        }
    )
    db.settlements[record["id"]] = record
    return success_object(public(record), status=201)


@bp.route("/harvest/contracts/<contractId>/settlements", methods=["GET"])
def list_settlements_for_contract(contractId):
    require_roles(*ALL_ROLES)
    contract = get_contract_or_404(contractId)
    pagination = parse_pagination(request.args)
    items = [s for s in db.settlements.values() if s["contract_id"] == contract["id"]]
    items.sort(key=sort_key)
    page, pag = paginate(items, pagination)
    return success_list([public(r) for r in page], pag)


@bp.route("/harvest/settlements", methods=["GET"])
def list_settlements():
    require_roles(*ALL_ROLES)
    pagination = parse_pagination(request.args)
    contract_id = request.args.get("contract_id")
    season_id = request.args.get("season_id")
    items = list(db.settlements.values())
    if contract_id is not None:
        items = [s for s in items if s["contract_id"] == contract_id]
    if season_id is not None:
        items = [s for s in items if s["season_id"] == season_id]
    items.sort(key=sort_key)
    page, pag = paginate(items, pagination)
    return success_list([public(r) for r in page], pag)


@bp.route("/harvest/settlements/<settlementId>", methods=["GET"])
def get_settlement(settlementId):
    require_roles(*ALL_ROLES)
    settlement = get_settlement_or_404(settlementId)
    return success_object(public(settlement))


@bp.route("/harvest/settlements/<settlementId>/issue", methods=["POST"])
def issue_settlement(settlementId):
    require_roles("BillingClerk")
    settlement = get_settlement_or_404(settlementId)
    # State legality (priority 4): settlement must be DRAFT.
    if settlement["status"] != "DRAFT":
        raise ApiError(
            ERR_SETTLEMENT_NOT_DRAFT, 409, "issue requires settlement DRAFT"
        )
    contract = get_contract_or_404(settlement["contract_id"])
    season = get_season_or_404(contract["season_id"])
    # Business (priority 11): contract must be HARVESTED — evaluated BEFORE
    # the OCC check per §2.6.
    if contract["status"] != "HARVESTED":
        raise ApiError(
            ERR_CONTRACT_NOT_HARVESTED,
            409,
            "settlement.issue requires contract HARVESTED",
        )
    if season["status"] != "SETTLING":
        raise ApiError(
            ERR_SEASON_NOT_SETTLING, 409, "issue requires season SETTLING"
        )
    # OCC (priority 13): expected_contract_version must match current.
    body = get_json_body()
    require_fields(body, ["expected_contract_version"])
    if not is_int(body["expected_contract_version"]):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "expected_contract_version must be an integer"
        )
    if body["expected_contract_version"] != contract["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            412,
            "expected_contract_version does not match the contract's current version",
        )

    # Compute and freeze the five amounts in pinned order:
    # base → fuel → hauling → moisture → total.
    tickets = _contract_tickets(contract["id"])
    base = settlement_base_amount(contract, tickets)
    fuel = fuel_surcharge_cents(season, base)
    hauling = sum(int(t.get("hauling_add_on_cents", 0)) for t in tickets)
    moisture = moisture_discount_cents(contract, tickets)
    total = settlement_total(base, fuel, hauling, moisture)

    settlement["base_amount_cents"] = base
    settlement["fuel_surcharge_cents"] = fuel
    settlement["hauling_add_on_total_cents"] = hauling
    settlement["moisture_discount_cents"] = moisture
    settlement["total_amount_cents"] = total
    settlement["issued_at"] = db.logical_clock_iso
    settlement["status"] = "ISSUED"
    touch(settlement)

    # Contract side effects: accumulate moisture discount; bump version.
    contract["moisture_discount_total_cents"] = int(
        contract.get("moisture_discount_total_cents", 0)
    ) + moisture
    touch(contract)
    return success_object(public(settlement))


@bp.route("/harvest/settlements/<settlementId>/mark-paid", methods=["POST"])
def mark_paid(settlementId):
    require_roles("BillingClerk")
    settlement = get_settlement_or_404(settlementId)
    if settlement["status"] != "ISSUED":
        raise ApiError(
            ERR_SETTLEMENT_NOT_ISSUED, 409, "mark-paid requires settlement ISSUED"
        )
    settlement["status"] = "PAID"
    touch(settlement)
    contract = get_contract_or_404(settlement["contract_id"])
    _settle_contract(contract)
    return success_object(public(settlement))


@bp.route("/harvest/settlements/<settlementId>/dispute", methods=["POST"])
def dispute_settlement(settlementId):
    require_roles("GrowerLiaison")
    settlement = get_settlement_or_404(settlementId)
    if settlement["status"] != "ISSUED":
        raise ApiError(
            ERR_SETTLEMENT_NOT_ISSUED, 409, "dispute requires settlement ISSUED"
        )
    settlement["status"] = "DISPUTED"
    touch(settlement)
    return success_object(public(settlement))


@bp.route("/harvest/settlements/<settlementId>/resolve", methods=["POST"])
def resolve_settlement(settlementId):
    require_roles("BillingClerk")
    settlement = get_settlement_or_404(settlementId)
    if settlement["status"] != "DISPUTED":
        raise ApiError(
            ERR_SETTLEMENT_NOT_DISPUTED, 409, "resolve requires settlement DISPUTED"
        )
    body = get_json_body()
    require_fields(body, ["resolution_note"])
    resolution_note = require_type(body, "resolution_note", "string")
    if not resolution_note.strip():
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "resolution_note must be a non-empty string"
        )
    settlement["status"] = "RESOLVED"
    touch(settlement)
    contract = get_contract_or_404(settlement["contract_id"])
    _settle_contract(contract)
    return success_object(public(settlement))
