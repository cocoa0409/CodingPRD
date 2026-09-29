"""Supervisory deviation requests during the heightened supervision window."""
from flask import Blueprint

import calc
import db
import response
import serialize
import validation as v
from errors import err
from middleware import authenticate, require_organizer_identity
from routes.helpers import must_get

bp = Blueprint("deviations", __name__)

METRICS = ("ASSET_GROWTH", "LOAN_GROWTH", "DEPOSIT_GROWTH", "BRANCH_COUNT")
DECISIONS = ("APPROVED", "DENIED", "ESCALATED")


@bp.post("/de-novo/deviation-requests")
def create_deviation():
    authenticate(("LeadOrganizer",))
    data = v.body()
    group_id = v.req_id(data, "group_id")
    plan_id = v.req_id(data, "baseline_plan_id")
    metric = v.req_enum(data, "metric", METRICS)
    actual_value = v.req_int(data, "actual_value", 0, None)
    narrative = v.req_str(data, "narrative", 20, 500)
    group = must_get("groups", group_id)
    plan = must_get("plans", plan_id)
    require_organizer_identity(group["id"])
    # PRD 318/332: the supervision year is refreshed as the first step of creation.
    calc.recompute_supervision(group)
    year_index = group["supervision_year_index"]
    if group["stage"] != "OPEN":
        raise err("ERR_GROUP_NOT_OPEN")
    if plan["group_id"] != group["id"] or plan["status"] != "PINNED":
        raise err("ERR_BASELINE_PLAN_NOT_PINNED")
    for row in calc.deviations_of(group["id"]):
        if (row["status"] == "SUBMITTED"
                and row["metric"] == metric
                and row["supervision_year_index_at_request"] == year_index):
            raise err("ERR_DEVIATION_ALREADY_PENDING")
    if not 1 <= year_index <= calc.SUPERVISION_YEARS:
        raise err("ERR_SUPERVISION_WINDOW_EXPIRED")
    baseline, deviation_bps, requires_approval = calc.deviation_magnitude(
        plan, metric, actual_value, year_index)
    deviation = db.insert("deviations", {
        "group_id": group["id"],
        "baseline_plan_id": plan["id"],
        "metric": metric,
        "actual_value": actual_value,
        "narrative": narrative,
        "supervision_year_index_at_request": year_index,
        "baseline_value": baseline,
        "deviation_bps": deviation_bps,
        "requires_regulator_approval": requires_approval,
        "status": "SUBMITTED" if requires_approval else "AUTO_ACCEPTED",
        "decision_note": None,
    })
    db.touch(group)
    db.commit()
    return response.object_response(serialize.deviation(deviation), 201)


@bp.post("/de-novo/deviation-requests/<deviation_id>/decision")
def decide_deviation(deviation_id):
    authenticate(("CharteringExaminer",))
    data = v.body()
    decision = v.req_enum(data, "decision", DECISIONS)
    decision_note = v.opt_str(data, "decision_note", 1, 500)
    deviation = must_get("deviations", deviation_id)
    if deviation["status"] != "SUBMITTED":
        raise err("ERR_DEVIATION_NOT_DECIDABLE")
    if decision == "ESCALATED" and deviation["deviation_bps"] < calc.DEVIATION_ESCALATION_THRESHOLD_BPS:
        raise err("ERR_ESCALATION_THRESHOLD_NOT_MET")
    # PRD 332: the window check applies equally to deciding, and PRD 318 keeps the
    # clock from mutating rows, so the index is derived here without persisting it.
    group = db.get("groups", deviation["group_id"])
    year_index = calc.supervision_year_index(group, db.clock()) if group else 0
    if not 1 <= year_index <= calc.SUPERVISION_YEARS:
        raise err("ERR_SUPERVISION_WINDOW_EXPIRED")
    deviation["status"] = decision
    deviation["decision_note"] = decision_note
    db.touch(deviation)
    db.commit()
    return response.object_response(serialize.deviation(deviation))
