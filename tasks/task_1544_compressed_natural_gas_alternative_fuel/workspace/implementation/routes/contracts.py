"""SupplyContract and MonthlySettlement endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import STORE, new_id, now_utc, month_of
from errors import (
    ApiError,
    ERR_FLEET_ACCOUNT_NOT_FOUND,
    ERR_STATION_NOT_FOUND,
    ERR_SUPPLY_CONTRACT_NOT_FOUND,
    ERR_MONTHLY_SETTLEMENT_NOT_FOUND,
    ERR_CONTRACT_NOT_DRAFT,
    ERR_CONTRACT_ALREADY_ACTIVE,
    ERR_ACCOUNT_NOT_ACTIVE,
    ERR_STATION_NOT_ACTIVE,
    ERR_INVALID_TIME_RANGE,
    ERR_MONTH_NOT_CLOSED,
    ERR_MONTH_OUT_OF_CONTRACT,
    ERR_MONTH_ALREADY_SETTLED,
    ERR_ACCOUNT_OWNERSHIP_MISMATCH,
)
from middleware import get_caller, require_role, check_account_ownership
from response import success_object, success_list
from serializers import supply_contract_out, monthly_settlement_out
from services.core import touch
from services.pricing import compute_settlement
from validators import (
    body, require_fields, require_string, require_positive_int,
    require_positive_number, require_nonnegative_int, require_month,
    parse_pagination, paginate,
)

bp = Blueprint("contracts", __name__)

_READ = ["NetworkOperator", "StationManager", "ComplianceOfficer", "FleetAccountManager"]


def get_contract_or_404(cid: str) -> dict:
    c = STORE.supply_contracts.get(cid)
    if c is None:
        raise ApiError(ERR_SUPPLY_CONTRACT_NOT_FOUND, 404, "Supply contract id does not exist")
    return c


@bp.post("/cng/supply-contracts")
def create_supply_contract():
    caller = get_caller()
    require_role(caller, ["NetworkOperator"])
    data = body()
    require_fields(data, ["fleet_account_id", "station_id", "committed_monthly_gge",
                          "contract_price_per_gge_cents", "shortfall_tier1_rate_cents",
                          "shortfall_tier2_rate_cents", "start_month", "end_month"])
    fleet_account_id = require_string(data, "fleet_account_id")
    station_id = require_string(data, "station_id")
    committed = require_positive_number(data, "committed_monthly_gge")
    price = require_positive_int(data, "contract_price_per_gge_cents")
    t1 = require_nonnegative_int(data, "shortfall_tier1_rate_cents")
    t2 = require_nonnegative_int(data, "shortfall_tier2_rate_cents")
    start_month = require_month(data, "start_month")
    end_month = require_month(data, "end_month")

    # Existence (stage 4)
    if fleet_account_id not in STORE.fleet_accounts:
        raise ApiError(ERR_FLEET_ACCOUNT_NOT_FOUND, 404, "Fleet account id does not exist")
    if station_id not in STORE.stations:
        raise ApiError(ERR_STATION_NOT_FOUND, 404, "Station id does not exist")

    # Temporal (stage 9)
    if end_month < start_month:
        raise ApiError(ERR_INVALID_TIME_RANGE, 422,
                       "end_month must not precede start_month")

    now = now_utc()
    contract = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "fleet_account_id": fleet_account_id,
        "station_id": station_id,
        "committed_monthly_gge": committed,
        "contract_price_per_gge_cents": price,
        "shortfall_tier1_rate_cents": t1,
        "shortfall_tier2_rate_cents": t2,
        "start_month": start_month,
        "end_month": end_month,
        "status": "DRAFT",
    }
    STORE.supply_contracts[contract["id"]] = contract
    return success_object(supply_contract_out(contract), status=201)


@bp.get("/cng/supply-contracts")
def list_supply_contracts():
    caller = get_caller()
    require_role(caller, _READ)
    limit, offset = parse_pagination()
    fleet_account_id = request.args.get("fleet_account_id")
    station_id = request.args.get("station_id")
    status = request.args.get("status")
    items = sorted(STORE.supply_contracts.values(), key=lambda c: (c["created_at"], c["id"]))
    if fleet_account_id is not None:
        items = [c for c in items if c["fleet_account_id"] == fleet_account_id]
    if station_id is not None:
        items = [c for c in items if c["station_id"] == station_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if caller.role == "FleetAccountManager":
        items = [c for c in items if c["fleet_account_id"] == caller.user_id]
    page, total = paginate(items, limit, offset)
    return success_list([supply_contract_out(c) for c in page], limit, offset, total)


@bp.get("/cng/supply-contracts/<contractId>")
def get_supply_contract(contractId: str):
    caller = get_caller()
    require_role(caller, _READ)
    contract = get_contract_or_404(contractId)
    if caller.role == "FleetAccountManager":
        check_account_ownership(caller, contract["fleet_account_id"])
    return success_object(supply_contract_out(contract))


@bp.post("/cng/supply-contracts/<contractId>/activate")
def activate_contract(contractId: str):
    caller = get_caller()
    require_role(caller, ["NetworkOperator"])
    contract = get_contract_or_404(contractId)
    if contract["status"] != "DRAFT":
        raise ApiError(ERR_CONTRACT_NOT_DRAFT, 409,
                       "Contract activate requires DRAFT status")
    account = STORE.fleet_accounts.get(contract["fleet_account_id"])
    if account is None or account["status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_NOT_ACTIVE, 409,
                       "Contract activate requires an ACTIVE account")
    station = STORE.stations.get(contract["station_id"])
    if station is None or station["status"] != "ACTIVE":
        raise ApiError(ERR_STATION_NOT_ACTIVE, 409,
                       "Contract activate requires an ACTIVE station")
    for c in STORE.supply_contracts.values():
        if (c["id"] != contractId and c["status"] == "ACTIVE"
                and c["fleet_account_id"] == contract["fleet_account_id"]
                and c["station_id"] == contract["station_id"]):
            raise ApiError(ERR_CONTRACT_ALREADY_ACTIVE, 409,
                           "Another ACTIVE contract already covers this account-station pair")
    contract["status"] = "ACTIVE"
    touch(contract)
    return success_object(supply_contract_out(contract))


@bp.post("/cng/supply-contracts/<contractId>/settle-month")
def settle_month(contractId: str):
    caller = get_caller()
    require_role(caller, ["NetworkOperator"])
    data = body()
    require_fields(data, ["month"])
    month = require_month(data, "month")
    contract = get_contract_or_404(contractId)

    # Uniqueness (stage 8): (contract, month) not already settled
    for s in STORE.monthly_settlements.values():
        if s["supply_contract_id"] == contractId and s["month"] == month:
            raise ApiError(ERR_MONTH_ALREADY_SETTLED, 409,
                           "A MonthlySettlement already exists for this contract and month")
    # Temporal (stage 9)
    current_month = month_of(now_utc())
    if not month < current_month:
        raise ApiError(ERR_MONTH_NOT_CLOSED, 409,
                       "settle-month only allowed for months strictly before the current logical month")
    if not (contract["start_month"] <= month <= contract["end_month"]):
        raise ApiError(ERR_MONTH_OUT_OF_CONTRACT, 409,
                       "Settled month outside contract span")

    delivered, shortfall, penalty = compute_settlement(contract, month)
    now = now_utc()
    settlement = {
        "id": new_id(),
        "created_at": now,
        "supply_contract_id": contractId,
        "month": month,
        "delivered_gge": delivered,
        "shortfall_gge": shortfall,
        "penalty_cents": penalty,
        "settled_at": now,
    }
    STORE.monthly_settlements[settlement["id"]] = settlement

    account = STORE.fleet_accounts.get(contract["fleet_account_id"])
    if account is not None and penalty != 0:
        account["outstanding_balance_cents"] += penalty
        touch(account)
    elif account is not None:
        # Penalty of zero still posts (no balance change); version bump per spec:
        # "posts penalty_cents to FleetAccount.outstanding_balance_cents
        #  (FleetAccount.version += 1)" — a zero penalty is still a posting.
        account["outstanding_balance_cents"] += 0
        touch(account)

    return success_object(monthly_settlement_out(settlement), status=201)


@bp.get("/cng/monthly-settlements")
def list_monthly_settlements():
    caller = get_caller()
    require_role(caller, _READ)
    limit, offset = parse_pagination()
    supply_contract_id = request.args.get("supply_contract_id")
    month = request.args.get("month")
    items = sorted(STORE.monthly_settlements.values(), key=lambda s: (s["created_at"], s["id"]))
    if supply_contract_id is not None:
        items = [s for s in items if s["supply_contract_id"] == supply_contract_id]
    if month is not None:
        items = [s for s in items if s["month"] == month]
    if caller.role == "FleetAccountManager":
        # scope via contract's account
        items = [
            s for s in items
            if (STORE.supply_contracts.get(s["supply_contract_id"]) or {}).get("fleet_account_id") == caller.user_id
        ]
    page, total = paginate(items, limit, offset)
    return success_list([monthly_settlement_out(s) for s in page], limit, offset, total)


@bp.get("/cng/monthly-settlements/<settlementId>")
def get_monthly_settlement(settlementId: str):
    caller = get_caller()
    require_role(caller, _READ)
    s = STORE.monthly_settlements.get(settlementId)
    if s is None:
        raise ApiError(ERR_MONTHLY_SETTLEMENT_NOT_FOUND, 404,
                       "Monthly settlement id does not exist")
    if caller.role == "FleetAccountManager":
        contract = STORE.supply_contracts.get(s["supply_contract_id"])
        if contract is None or contract["fleet_account_id"] != caller.user_id:
            raise ApiError(ERR_ACCOUNT_OWNERSHIP_MISMATCH, 403,
                           "FleetAccountManager may only view settlements for own account")
    return success_object(monthly_settlement_out(s))
