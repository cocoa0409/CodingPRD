"""DamageReport endpoints: assessment, charge, waive."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_RESOURCE_NOT_FOUND,
    ERR_SETTLEMENT_NOT_DRAFT,
    ERR_VALUATION_METHOD_INVALID,
    ERR_REPAIR_QUOTE_REQUIRED,
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
from util import get_json_body, optional_field, require_enum, serialize

bp = Blueprint("damage_reports", __name__)

REPORT_STATES = {"FILED", "ASSESSED", "CHARGED", "WAIVED"}
REPORT_TERMINAL = {"CHARGED", "WAIVED"}
REPORT_TO_OWNERS = {
    "CHARGED": {"WarehouseChief"},
    "WAIVED": {"ProductionManager"},
    # ASSESSED is reached via POST /api/damage-reports/{id}/assess only.
}
REPORT_DECLARED = {
    "FILED": set(),
    "ASSESSED": {"CHARGED", "WAIVED"},
    "CHARGED": {"WAIVED"},
}

VALUATION_METHODS = {"DEPRECIATED", "REPAIR_QUOTE"}


def get_report_or_404(report_id: str) -> dict:
    report = db.damage_reports.get(report_id)
    if report is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "DamageReport id does not exist")
    return report


def _settlement_for(production_id: str):
    for settlement in db.settlements.values():
        if settlement["production_id"] == production_id:
            return settlement
    return None


@bp.route("/damage-reports/<report_id>", methods=["GET"])
@require_roles("Any")
def get_report(report_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_report_or_404(report_id)))


@bp.route("/damage-reports/<report_id>/assess", methods=["POST"])
@require_roles("WarehouseChief")
def assess_report(report_id: str, _user_id: str, _role: str):
    body = get_json_body()
    valuation_method = require_enum(body, "valuation_method", VALUATION_METHODS)
    repair_quote = optional_field(body, "repair_quote_cents", None)
    if repair_quote is not None:
        if isinstance(repair_quote, bool) or not isinstance(repair_quote, int) or repair_quote <= 0:
            raise_err(ERR_INVALID_REQUEST, "repair_quote_cents must be a positive integer")
    # DEPRECIATED valuation forbids the quote field entirely (schema).
    if valuation_method == "DEPRECIATED" and repair_quote is not None:
        raise_err(ERR_INVALID_REQUEST, "repair_quote_cents is forbidden for DEPRECIATED valuation")

    report = get_report_or_404(report_id)
    if report["status"] in REPORT_TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, f"Resource is in terminal state {report['status']}")
    if report["status"] != "FILED":
        raise_err(ERR_INVALID_STATE, "Only a FILED report may be assessed")

    # Fiscal gates, evaluated in order.
    if report["report_type"] == "LOSS" and valuation_method != "DEPRECIATED":
        raise_err(ERR_VALUATION_METHOD_INVALID, "LOSS reports accept only DEPRECIATED valuation")
    if valuation_method == "REPAIR_QUOTE" and repair_quote is None:
        raise_err(ERR_REPAIR_QUOTE_REQUIRED, "REPAIR_QUOTE valuation requires repair_quote_cents")

    report["valuation_method"] = valuation_method
    report["repair_quote_cents"] = repair_quote

    entry = db.pull_list_entries.get(report["pull_list_entry_id"])
    asset = db.assets.get(entry["asset_id"]) if entry is not None else None

    report["assessed_charge_cents"] = calc.compute_damage_charge(report, asset)

    # The entry leaves OUT; billing ends at the assessment clock time. The
    # asset follows the entry's terminal condition.
    now = db.get_current_utc()
    if entry is not None and entry["status"] == "OUT":
        entry["returned_at"] = now
        entry["rental_charge_cents"] = calc.compute_rental_charge(
            entry["out_at"], now, asset["daily_rate_cents"]
        )
        entry["status"] = "DAMAGED" if report["report_type"] == "DAMAGE" else "LOST"
        db.touch(entry)
        if asset is not None:
            asset["status"] = "DAMAGED" if report["report_type"] == "DAMAGE" else "LOST"
            db.touch(asset)

    report["status"] = "ASSESSED"
    db.touch(report)
    if entry is not None:
        calc.refresh_posture(db.productions.get(entry["production_id"]))
    return success_object(serialize(report))


@bp.route("/damage-reports/<report_id>/transition", methods=["POST"])
@require_roles("ProductionManager", "WarehouseChief")
def transition_report(report_id: str, _user_id: str, _role: str):
    body = get_json_body()
    to = parse_to(body, REPORT_STATES)
    check_transition_owner(to, REPORT_TO_OWNERS, _role)
    report = get_report_or_404(report_id)
    check_terminal(report, REPORT_TERMINAL, to, REPORT_DECLARED)
    check_declared(report, to, REPORT_DECLARED)

    settlement = _settlement_for(report["production_id"])

    if to == "CHARGED":
        if settlement is None or settlement["status"] != "DRAFT":
            raise_err(ERR_SETTLEMENT_NOT_DRAFT, "Charging requires the settlement to be DRAFT")
        report["status"] = "CHARGED"
        db.touch(report)
        settlement["damage_total_cents"] += report["assessed_charge_cents"]
        settlement["grand_total_cents"] = (
            settlement["labor_total_cents"]
            + settlement["equipment_total_cents"]
            + settlement["damage_total_cents"]
        )
        db.touch(settlement)
        return success_object(serialize(report))

    # to == "WAIVED"
    if report["status"] == "CHARGED":
        # Compensation path: credit the charge back out of the settlement.
        if settlement is None or settlement["status"] != "DRAFT":
            raise_err(ERR_SETTLEMENT_NOT_DRAFT, "Waiving a CHARGED report requires the settlement to be DRAFT")
        report["status"] = "WAIVED"
        db.touch(report)
        settlement["damage_total_cents"] -= report["assessed_charge_cents"]
        settlement["grand_total_cents"] = (
            settlement["labor_total_cents"]
            + settlement["equipment_total_cents"]
            + settlement["damage_total_cents"]
        )
        db.touch(settlement)
        return success_object(serialize(report))

    # Waiving from ASSESSED carries no settlement gate.
    report["status"] = "WAIVED"
    db.touch(report)
    return success_object(serialize(report))
