"""Settlement endpoints: create, finalize, recalculate, authorize-distribution."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_DISPUTE_WINDOW_OPEN,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
    ERR_RECONCILIATION_RUNOUT_INCOMPLETE,
    ERR_SETTLEMENT_EXISTS,
    ERR_SETTLEMENT_STALE,
    ERR_YEAR_NOT_RECONCILING,
)
from middleware import ALL_ROLES, check_group_scope, require_roles
from response import success_list, success_object
from services import calculations as calc
from services import engine
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    reject_unknown_fields,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("settlements", __name__)


def _settlement_group_id(settlement: dict) -> str | None:
    year = db.performance_years.get(settlement["performance_year_id"])
    if year is None:
        return None
    contract = db.contracts.get(year["contract_id"])
    return contract["practice_group_id"] if contract else None


def _get_settlement_or_404(settlement_id: str) -> dict:
    settlement = db.settlements.get(settlement_id)
    if settlement is None:
        raise_err(ERR_NOT_FOUND, "Settlement id does not exist")
    return settlement


@bp.route("/vbc/settlements", methods=["POST"])
@require_roles("SettlementOfficer")
def create_settlement(_user_id: str, _role: str):
    body = get_json_body()
    raw_year = body.get("performance_year_id")
    if isinstance(raw_year, str) and raw_year != "" and raw_year not in db.performance_years:
        raise_err(ERR_NOT_FOUND, "performance_year_id does not exist")
    reject_unknown_fields(body, {"performance_year_id"})
    performance_year_id = require_string(body, "performance_year_id")
    if performance_year_id not in db.performance_years:
        raise_err(ERR_NOT_FOUND, "performance_year_id does not exist")

    year = db.performance_years[performance_year_id]
    # Priority 6 (state): year must be RECONCILING.
    if year["year_status"] != "RECONCILING":
        raise_err(ERR_YEAR_NOT_RECONCILING, "Settlement create requires the year to be RECONCILING")
    # Priority 11: at most one non-VOID settlement per year.
    for settlement in db.settlements.values():
        if settlement["performance_year_id"] == performance_year_id and settlement["settlement_status"] != "VOID":
            raise_err(ERR_SETTLEMENT_EXISTS, "A non-VOID settlement already exists for the year")

    contract = engine.contract_of_year(year)
    seq = max(
        (s["settlement_seq"] for s in db.settlements.values() if s["performance_year_id"] == performance_year_id),
        default=0,
    ) + 1
    settlement = {
        "performance_year_id": performance_year_id,
        "settlement_seq": seq,
        "settlement_status": "PROVISIONAL",
        "finalized_on": None,
        "finalized_by_user_id": None,
        "needs_recompute": False,
    }
    # The full chain is computed at create from the year's stored rollups.
    settlement.update(calc.compute_settlement_chain(contract, year, None))
    db.stamp_new(settlement)
    db.settlements[settlement["id"]] = settlement
    return success_object(settlement, 201)


@bp.route("/vbc/settlements", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_settlements(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.settlements.values()))
    items = apply_filters(items, ["performance_year_id", "settlement_status"])
    if _role == "PracticeGroupRep":
        items = [s for s in items if _settlement_group_id(s) == _user_id]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/vbc/settlements/<settlement_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_settlement(settlement_id: str, _user_id: str, _role: str):
    settlement = _get_settlement_or_404(settlement_id)
    # Priority 4: PracticeGroupRep scope.
    check_group_scope(_user_id, _role, _settlement_group_id(settlement))
    return success_object(settlement)


@bp.route("/vbc/settlements/<settlement_id>/finalize", methods=["POST"])
@require_roles("SettlementOfficer")
def finalize_settlement(settlement_id: str, _user_id: str, _role: str):
    settlement = _get_settlement_or_404(settlement_id)
    # Priority 6 (state) before priority 8 (temporal runout).
    if settlement["settlement_status"] != "PROVISIONAL":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a PROVISIONAL settlement can be finalized")
    if settlement["needs_recompute"]:
        raise_err(ERR_SETTLEMENT_STALE, "Settlement is stale; call recalculate first")
    year = db.performance_years[settlement["performance_year_id"]]
    runout_end = db.add_days(db.parse_date(year["period_end"]), calc.RECONCILIATION_RUNOUT_DAYS)
    if db.clock_date() < runout_end:
        raise_err(ERR_RECONCILIATION_RUNOUT_INCOMPLETE, "Reconciliation runout has not elapsed")

    # Final runout variant: recompute every computed field from current data
    # (actuals only; cost_measurement fires on finalize).
    engine.recompute_settlement_fields(settlement, recompute_year_cost=True)
    settlement["finalized_on"] = db.clock_date_iso()
    settlement["finalized_by_user_id"] = _user_id
    settlement["settlement_status"] = "FINALIZED"
    db.touch(settlement)
    return success_object(settlement)


@bp.route("/vbc/settlements/<settlement_id>/recalculate", methods=["POST"])
@require_roles("SettlementOfficer")
def recalculate_settlement(settlement_id: str, _user_id: str, _role: str):
    settlement = _get_settlement_or_404(settlement_id)
    if settlement["settlement_status"] != "PROVISIONAL":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a PROVISIONAL settlement can be recalculated")
    engine.recompute_settlement_fields(settlement, recompute_year_cost=True)
    settlement["needs_recompute"] = False
    db.touch(settlement)
    return success_object(settlement)


@bp.route("/vbc/settlements/<settlement_id>/authorize-distribution", methods=["POST"])
@require_roles("SettlementOfficer")
def authorize_distribution(settlement_id: str, _user_id: str, _role: str):
    settlement = _get_settlement_or_404(settlement_id)
    # Priority 6 (state) before priority 8 (temporal dispute window).
    if settlement["settlement_status"] != "FINALIZED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a FINALIZED settlement can be authorized for distribution")
    window_end = db.add_days(db.parse_date(settlement["finalized_on"]), calc.DISPUTE_WINDOW_DAYS)
    if db.clock_date() <= window_end:
        raise_err(ERR_DISPUTE_WINDOW_OPEN, "Dispute window is still open")

    year = db.performance_years[settlement["performance_year_id"]]
    contract = engine.contract_of_year(year)
    allocations = calc.compute_distribution(contract, year, settlement)

    for alloc in allocations:
        remittance = {
            "settlement_id": settlement["id"],
            "practice_id": alloc["practice_id"],
            "practice_member_months": alloc["practice_member_months"],
            "amount_cents": alloc["amount_cents"],
            "remittance_status": "SCHEDULED",
            "paid_on": None,
        }
        db.stamp_new(remittance)
        db.distribution_remittances[remittance["id"]] = remittance

    settlement["undistributed_balance_cents"] = calc.recompute_undistributed(settlement)
    if allocations:
        settlement["settlement_status"] = "AUTHORIZED"
    else:
        # net_payable <= 0 (or no allocation weights): straight to DISTRIBUTED.
        settlement["settlement_status"] = "DISTRIBUTED"
    db.touch(settlement)
    return success_object(settlement)
