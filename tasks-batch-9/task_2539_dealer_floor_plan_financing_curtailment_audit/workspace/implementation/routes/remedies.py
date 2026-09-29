"""Remedy execution: the three-rung ladder of PRD 3.8."""

from flask import Blueprint

import db
import lookup
import middleware
import response
import validate
from errors import ApiError
from services import ledger, serial, spec

bp = Blueprint("remedies", __name__)


@bp.route("/floorplan/remedy-actions/<remedy_id>/execute", methods=["POST"])
def execute_remedy(remedy_id):
    user_id, _ = middleware.require(middleware.CREDIT_RISK_MANAGER)
    remedy = lookup.remedy(remedy_id)
    validate.body()

    if remedy["status"] != "ISSUED":
        raise ApiError("ERR_REMEDY_NOT_ISSUED")
    if user_id == remedy["issued_by_user_id"]:
        raise ApiError("ERR_SOD_REMEDY_EXECUTOR")

    dealer = db.get("dealers", remedy["dealer_id"])
    line = ledger.dealer_line(remedy["dealer_id"])
    action_type = remedy["action_type"]

    if action_type == "LINE_SUSPENSION":
        if dealer["status"] != "ACTIVE":
            raise ApiError("ERR_DEALER_NOT_ACTIVE")
        if line is None or line["status"] != "ACTIVE":
            raise ApiError("ERR_CREDIT_LINE_NOT_ACTIVE")
        ledger.suspend_line(line, dealer, "REMEDY_ACTION")

    elif action_type == "REPOSSESSION":
        sot_units = [
            u for u in ledger.dealer_units(dealer["id"]) if u["funding_status"] == "SOT_OPEN"
        ]
        if dealer["status"] != "SUSPENDED" or int(dealer["open_sot_incident_count"]) < 1:
            raise ApiError("ERR_REMEDY_NOT_JUSTIFIED")
        charged_off_total = 0
        repossessed = 0
        for unit in sot_units:
            unit_line = ledger.unit_line(unit)
            for incident in ledger.unit_incidents(unit["id"], ("OPEN",)):
                incident["status"] = "CHARGED_OFF"
                incident["charged_off_at"] = db.now_str()
                incident["resolution_reason_code"] = "REPOSSESSION_CHARGE_OFF"
                db.touch(incident)
            principal = int(unit["outstanding_principal_cents"])
            if unit_line is not None:
                unit_line["charged_off_principal_cents"] = (
                    int(unit_line["charged_off_principal_cents"]) + principal
                )
                db.touch(unit_line)
            unit["outstanding_principal_cents"] = 0
            unit["funding_status"] = "REPOSSESSED"
            db.touch(unit)
            for obligation in ledger.unit_obligations(unit["id"], spec.OPEN_OBLIGATION_STATUSES):
                obligation["status"] = "CANCELLED"
                db.touch(obligation)
            charged_off_total += principal
            repossessed += 1
        remedy["units_repossessed_count"] = repossessed
        remedy["principal_charged_off_cents"] = charged_off_total
        dealer["status"] = "DEFAULTED"

    else:  # LINE_TERMINATION
        if dealer["status"] != "DEFAULTED":
            raise ApiError("ERR_REMEDY_NOT_JUSTIFIED")
        if line is not None and line["status"] in ("ACTIVE", "SUSPENDED"):
            line["status"] = "TERMINATED"
            db.touch(line)
        dealer["status"] = "TERMINATED"

    remedy["status"] = "EXECUTED"
    remedy["executed_by_user_id"] = user_id
    remedy["executed_at"] = db.now_str()
    db.touch(remedy)

    ledger.recompute_availability(line)
    if action_type == "LINE_TERMINATION" and line is not None:
        line["available_credit_cents"] = 0
    ledger.recompute_dealer_counters(dealer)
    ledger.recompute_risk(dealer)
    db.touch(dealer)
    return response.ok(serial.remedy(remedy))
