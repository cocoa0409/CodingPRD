from decimal import Decimal, ROUND_FLOOR

from flask import Blueprint, request

from db import db
from decimalutil import ceil_value, floor_div
from errors import ApiError
from helpers import (
    fetch_or_404, get_json_body, new_common_fields, paginate,
    parse_pagination, require_fields, require_enum, require_type,
    sorted_by_created, strip_internal, touch,
)
from middleware import require_role
from response import success_array, success_object
from services import recompute_risk_tier_value, pod_set_operational_status
from timeutil import current_clock, parse_iso8601

bp = Blueprint("pods", __name__)

SITE_TYPES = {"FIXED_POD", "MOBILE_POD", "DRIVE_THROUGH", "CLOSED_POD"}
ALL_ROLES = ["PublicHealthAdmin", "LogisticsCoordinator", "MutualAidPartner", "ClinicalLead", "Volunteer"]

STAFF_PER_LANE = 2
SURGE_LANE_THRESHOLD = 6
SURGE_BONUS_MULTIPLIER = 1.15
NO_SHOW_RATE = 0.10


@bp.route("/pods", methods=["POST"])
@require_role("PublicHealthAdmin")
def create_pod():
    body = get_json_body()
    require_fields(body, ["hazard_plan_id", "site_name", "site_type", "address",
                           "staffing_capacity_lanes", "lane_throughput_rate_per_hour"])
    fetch_or_404(db.hazard_plans, body["hazard_plan_id"], "HazardPlan")
    require_type(body["site_name"], str, "site_name")
    require_type(body["site_type"], str, "site_type")
    require_enum(body["site_type"], SITE_TYPES, "site_type")
    require_type(body["address"], str, "address")
    require_type(body["staffing_capacity_lanes"], int, "staffing_capacity_lanes")
    require_type(body["lane_throughput_rate_per_hour"], int, "lane_throughput_rate_per_hour")
    if body["staffing_capacity_lanes"] <= 0:
        raise ApiError("ERR_VALIDATION", "staffing_capacity_lanes must be > 0.", 400)
    if body["lane_throughput_rate_per_hour"] <= 0:
        raise ApiError("ERR_VALIDATION", "lane_throughput_rate_per_hour must be > 0.", 400)

    row = new_common_fields()
    row.update({
        "hazard_plan_id": body["hazard_plan_id"],
        "site_name": body["site_name"],
        "site_type": body["site_type"],
        "address": body["address"],
        "staffing_capacity_lanes": body["staffing_capacity_lanes"],
        "lane_throughput_rate_per_hour": body["lane_throughput_rate_per_hour"],
        "operational_status": "STAGING",
        "risk_tier": "STANDARD",
        "queue_backlog_count": 0,
        "open_allocation_request_count": 0,
        "committed_staff_hours": 0,
    })
    db.pods[row["id"]] = row
    return success_object(strip_internal(row), 201)


@bp.route("/pods/<pod_id>", methods=["GET"])
@require_role(*ALL_ROLES)
def get_pod(pod_id):
    row = fetch_or_404(db.pods, pod_id, "POD")
    return success_object(strip_internal(row))


@bp.route("/pods", methods=["GET"])
@require_role(*ALL_ROLES)
def list_pods():
    limit, offset = parse_pagination(request.args)
    hazard_plan_id = request.args.get("hazard_plan_id")
    operational_status = request.args.get("operational_status")
    rows = list(db.pods.values())
    if hazard_plan_id:
        rows = [r for r in rows if r["hazard_plan_id"] == hazard_plan_id]
    if operational_status:
        rows = [r for r in rows if r["operational_status"] == operational_status]
    rows = sorted_by_created(rows)
    items, total = paginate(rows, limit, offset)
    return success_array(items, limit, offset, total)


@bp.route("/pods/<pod_id>/open", methods=["POST"])
@require_role("PublicHealthAdmin")
def open_pod(pod_id):
    pod = fetch_or_404(db.pods, pod_id, "POD")
    if pod["operational_status"] != "STAGING":
        raise ApiError("ERR_INVALID_STATE", "POD must be STAGING to open.", 409)
    plan = db.hazard_plans.get(pod["hazard_plan_id"])
    if plan is None or plan["status"] != "ACTIVATED":
        raise ApiError("ERR_HAZARD_PLAN_NOT_ACTIVATED", "Owning HazardPlan must be ACTIVATED to open this POD.", 409)
    pod_set_operational_status(pod, "OPERATIONAL")
    return success_object(strip_internal(pod))


@bp.route("/pods/<pod_id>/restrict", methods=["POST"])
@require_role("PublicHealthAdmin")
def restrict_pod(pod_id):
    pod = fetch_or_404(db.pods, pod_id, "POD")
    if pod["operational_status"] != "OPERATIONAL":
        raise ApiError("ERR_INVALID_STATE", "POD must be OPERATIONAL to restrict.", 409)
    pod_set_operational_status(pod, "RESTRICTED")
    return success_object(strip_internal(pod))


@bp.route("/pods/<pod_id>/resume", methods=["POST"])
@require_role("PublicHealthAdmin")
def resume_pod(pod_id):
    pod = fetch_or_404(db.pods, pod_id, "POD")
    if pod["operational_status"] != "RESTRICTED":
        raise ApiError("ERR_INVALID_STATE", "POD must be RESTRICTED to resume.", 409)
    pod_set_operational_status(pod, "OPERATIONAL")
    return success_object(strip_internal(pod))


@bp.route("/pods/<pod_id>/close", methods=["POST"])
@require_role("PublicHealthAdmin")
def close_pod(pod_id):
    pod = fetch_or_404(db.pods, pod_id, "POD")
    if pod["operational_status"] not in ("STAGING", "OPERATIONAL", "RESTRICTED"):
        raise ApiError("ERR_INVALID_STATE", "POD is not in a closable state.", 409)
    shifts_here = [s for s in db.shift_assignments.values() if s["pod_id"] == pod_id]
    if any(s["status"] == "CHECKED_IN" for s in shifts_here):
        raise ApiError("ERR_POD_STAFF_ONSITE", "A staff member is still checked in at this POD.", 409)
    pod_set_operational_status(pod, "CLOSED")
    for s in shifts_here:
        if s["status"] in ("PENDING", "CONFIRMED"):
            s["status"] = "CANCELLED"
            touch(s)
    return success_object(strip_internal(pod))


@bp.route("/pods/<pod_id>/operational-metrics", methods=["GET"])
@require_role("PublicHealthAdmin", "LogisticsCoordinator", "ClinicalLead")
def pod_operational_metrics(pod_id):
    pod = fetch_or_404(db.pods, pod_id, "POD")
    countermeasure_id = request.args.get("countermeasure_id")
    countermeasure = db.countermeasures.get(countermeasure_id) if countermeasure_id else None
    if countermeasure is None:
        raise ApiError("ERR_COUNTERMEASURE_NOT_FOUND", "countermeasure_id not found.", 404)

    now = current_clock()

    def interval_contains_now(shift):
        start = parse_iso8601(shift["start_time"])
        end = parse_iso8601(shift["end_time"])
        return start <= now < end

    shifts_here = [s for s in db.shift_assignments.values() if s["pod_id"] == pod_id]
    current_count = sum(1 for s in shifts_here if s["status"] == "CHECKED_IN" and interval_contains_now(s))
    planned_count = sum(1 for s in shifts_here if s["status"] in ("CONFIRMED", "CHECKED_IN") and interval_contains_now(s))

    lanes_staffed_current = current_count // STAFF_PER_LANE
    lanes_staffed_planned = planned_count // STAFF_PER_LANE

    inventory_available = sum(
        lot["available_quantity"] for lot in db.inventory_lots.values()
        if lot["pod_id"] == pod_id and lot["countermeasure_id"] == countermeasure_id
    )
    hourly_capacity_by_inventory = floor_div(inventory_available, countermeasure["doses_required"])

    def variant_capacity(lanes_staffed):
        effective_lanes = min(lanes_staffed, pod["staffing_capacity_lanes"])
        hourly_capacity_by_staff = effective_lanes * pod["lane_throughput_rate_per_hour"]
        base_capacity = min(hourly_capacity_by_staff, hourly_capacity_by_inventory)
        if effective_lanes >= SURGE_LANE_THRESHOLD:
            surged = Decimal(base_capacity) * Decimal("1.15")
            return int(surged.to_integral_value(rounding=ROUND_FLOOR))
        return base_capacity

    current_throughput = variant_capacity(lanes_staffed_current)
    planned_throughput = variant_capacity(lanes_staffed_planned)

    events_here = [
        e for e in db.dispensing_events.values()
        if e["pod_id"] == pod_id and e["countermeasure_id"] == countermeasure_id
    ]
    pending_registrants = sum(1 for e in events_here if e["status"] in ("REGISTERED", "SCREENED", "DEFERRED"))
    provisional_demand_doses = ceil_value(pending_registrants * (1 - NO_SHOW_RATE) * countermeasure["doses_required"])
    final_demand_doses = sum(e["dose_count"] for e in events_here if e["status"] == "DISPENSED")

    data = {
        "current_throughput_capacity_per_hour": current_throughput,
        "planned_throughput_capacity_per_hour": planned_throughput,
        "provisional_demand_doses": provisional_demand_doses,
        "final_demand_doses": final_demand_doses,
    }
    return success_object(data)
