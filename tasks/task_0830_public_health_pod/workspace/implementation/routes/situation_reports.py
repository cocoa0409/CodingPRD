from decimal import Decimal

from flask import Blueprint, request

from db import db
from decimalutil import round_half_up
from errors import ApiError
from helpers import (
    fetch_or_404, get_json_body, new_id, paginate,
    parse_pagination, require_fields, require_type,
    sorted_by_created, strip_internal,
)
from middleware import require_role
from response import success_array, success_object
from timeutil import new_timestamp_iso

bp = Blueprint("situation_reports", __name__)

RED_THRESHOLD = Decimal("50.0")
YELLOW_THRESHOLD = Decimal("80.0")
ALL_ROLES = ["PublicHealthAdmin", "LogisticsCoordinator", "MutualAidPartner", "ClinicalLead", "Volunteer"]


@bp.route("/situation-reports", methods=["POST"])
@require_role("PublicHealthAdmin", "LogisticsCoordinator")
def create_situation_report():
    body = get_json_body()
    require_fields(body, ["hazard_plan_id", "report_period_label"])
    fetch_or_404(db.hazard_plans, body["hazard_plan_id"], "HazardPlan")
    require_type(body["report_period_label"], str, "report_period_label")
    narrative = body.get("narrative")

    plan_id = body["hazard_plan_id"]
    plan_pod_ids = {p["id"] for p in db.pods.values() if p["hazard_plan_id"] == plan_id}

    pods_operational_count = sum(1 for p in db.pods.values() if p["hazard_plan_id"] == plan_id and p["operational_status"] == "OPERATIONAL")
    pods_restricted_count = sum(1 for p in db.pods.values() if p["hazard_plan_id"] == plan_id and p["operational_status"] == "RESTRICTED")

    total_doses_dispensed = sum(
        e["dose_count"] for e in db.dispensing_events.values()
        if e["status"] == "DISPENSED" and e["pod_id"] in plan_pod_ids
    )
    total_on_hand_inventory = sum(
        lot["on_hand_quantity"] for lot in db.inventory_lots.values()
        if lot["pod_id"] in plan_pod_ids
    )

    plan_shifts = [s for s in db.shift_assignments.values() if s["pod_id"] in plan_pod_ids]
    denom = len(plan_shifts)
    if denom == 0:
        staffing_fill_rate_pct = 0
    else:
        filled = sum(1 for s in plan_shifts if s["status"] in ("CONFIRMED", "CHECKED_IN", "COMPLETED"))
        staffing_fill_rate_pct = round_half_up(Decimal(100 * filled) / Decimal(denom), 1)

    reimbursements = [
        Decimal(str(ar["reimbursement_cost_usd"])) for ar in db.allocation_requests.values()
        if ar["pod_id"] in plan_pod_ids and ar["source_type"] == "MUTUAL_AID" and ar["status"] == "FULFILLED"
    ]
    total_mutual_aid_reimbursement_usd = round_half_up(sum(reimbursements, Decimal(0)), 2)

    fill_rate_decimal = Decimal(str(staffing_fill_rate_pct))
    if pods_restricted_count >= 1 or fill_rate_decimal < RED_THRESHOLD:
        readiness_status = "RED"
    elif fill_rate_decimal < YELLOW_THRESHOLD:
        readiness_status = "YELLOW"
    else:
        readiness_status = "GREEN"

    row = {
        "id": new_id(),
        "created_at": new_timestamp_iso(),
        "_seq": db.next_seq(),
        "hazard_plan_id": plan_id,
        "report_period_label": body["report_period_label"],
        "pods_operational_count": pods_operational_count,
        "pods_restricted_count": pods_restricted_count,
        "total_doses_dispensed": total_doses_dispensed,
        "total_on_hand_inventory": total_on_hand_inventory,
        "staffing_fill_rate_pct": staffing_fill_rate_pct,
        "total_mutual_aid_reimbursement_usd": total_mutual_aid_reimbursement_usd,
        "readiness_status": readiness_status,
        "narrative": narrative,
    }
    db.situation_reports[row["id"]] = row
    return success_object(strip_internal(row), 201)


@bp.route("/situation-reports/<report_id>", methods=["GET"])
@require_role(*ALL_ROLES)
def get_situation_report(report_id):
    row = fetch_or_404(db.situation_reports, report_id, "SituationReport")
    return success_object(strip_internal(row))


@bp.route("/situation-reports", methods=["GET"])
@require_role(*ALL_ROLES)
def list_situation_reports():
    limit, offset = parse_pagination(request.args)
    hazard_plan_id = request.args.get("hazard_plan_id")
    rows = list(db.situation_reports.values())
    if hazard_plan_id:
        rows = [r for r in rows if r["hazard_plan_id"] == hazard_plan_id]
    rows = sorted_by_created(rows)
    items, total = paginate(rows, limit, offset)
    return success_array(items, limit, offset, total)
