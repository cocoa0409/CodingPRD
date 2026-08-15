"""SettlementStatement endpoints: issue, dispute, resolve, pay."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_RESOURCE_NOT_FOUND,
    ERR_UNRESOLVED_DAMAGE_REPORTS,
    ERR_ADJUSTMENT_OUT_OF_RANGE,
)
from middleware import require_roles
from response import success_object
from services import calculations as calc
from services.domain import (
    check_declared,
    check_terminal,
    check_transition_owner,
    parse_to,
)
from util import get_json_body, optional_int, serialize

bp = Blueprint("settlements", __name__)

SETTLEMENT_STATES = {"DRAFT", "ISSUED", "DISPUTED", "RESOLVED", "PAID"}
SETTLEMENT_TERMINAL = {"RESOLVED", "PAID"}
SETTLEMENT_TO_OWNERS = {
    "ISSUED": {"ProductionManager"},
    "DISPUTED": {"ClientContact"},
    "RESOLVED": {"ProductionManager"},
    "PAID": {"ProductionManager"},
}
SETTLEMENT_DECLARED = {
    "DRAFT": {"ISSUED"},
    "ISSUED": {"DISPUTED", "PAID"},
    "DISPUTED": {"RESOLVED"},
}


def get_settlement_or_404(settlement_id: str) -> dict:
    settlement = db.settlements.get(settlement_id)
    if settlement is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "SettlementStatement id does not exist")
    return settlement


def _settle_production(settlement: dict) -> None:
    """Fire the production's CLOSED -> SETTLED transition."""
    production = db.productions.get(settlement["production_id"])
    if production is not None and production["status"] == "CLOSED":
        production["status"] = "SETTLED"
        db.touch(production)


@bp.route("/settlements/<settlement_id>", methods=["GET"])
@require_roles("Any")
def get_settlement(settlement_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_settlement_or_404(settlement_id)))


@bp.route("/settlements/<settlement_id>/transition", methods=["POST"])
@require_roles("ProductionManager", "ClientContact")
def transition_settlement(settlement_id: str, _user_id: str, _role: str):
    body = get_json_body()
    to = parse_to(body, SETTLEMENT_STATES)
    check_transition_owner(to, SETTLEMENT_TO_OWNERS, _role)

    adjustment = 0
    if to == "RESOLVED":
        adjustment = optional_int(body, "dispute_adjustment_cents", 0)

    settlement = get_settlement_or_404(settlement_id)
    check_terminal(settlement, SETTLEMENT_TERMINAL, to, SETTLEMENT_DECLARED)
    check_declared(settlement, to, SETTLEMENT_DECLARED)

    if to == "ISSUED":
        for report in db.damage_reports.values():
            if report["production_id"] == settlement["production_id"] and report["status"] not in (
                "CHARGED",
                "WAIVED",
            ):
                raise_err(ERR_UNRESOLVED_DAMAGE_REPORTS, "Open damage reports block issuance")
        # FINAL variant: damage totals count CHARGED only and stop moving.
        totals = calc.settlement_live_totals(settlement["production_id"])
        settlement["labor_total_cents"] = totals["labor_total_cents"]
        settlement["equipment_total_cents"] = totals["equipment_total_cents"]
        settlement["damage_total_cents"] = totals["damage_total_cents"]
        settlement["grand_total_cents"] = totals["grand_total_cents"]
        settlement["status"] = "ISSUED"
        db.touch(settlement)
        return success_object(serialize(settlement))

    if to == "DISPUTED":
        settlement["status"] = "DISPUTED"
        db.touch(settlement)
        return success_object(serialize(settlement))

    if to == "RESOLVED":
        if abs(adjustment) > settlement["damage_total_cents"]:
            raise_err(ERR_ADJUSTMENT_OUT_OF_RANGE, "Adjustment exceeds damage_total_cents")
        settlement["dispute_adjustment_cents"] = adjustment
        settlement["grand_total_cents"] += adjustment
        settlement["status"] = "RESOLVED"
        db.touch(settlement)
        _settle_production(settlement)
        return success_object(serialize(settlement))

    # to == "PAID"
    settlement["status"] = "PAID"
    db.touch(settlement)
    _settle_production(settlement)
    return success_object(serialize(settlement))
