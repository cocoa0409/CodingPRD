"""RepairWorkOrder standalone endpoints: get / schedule / start / hold / resume /
complete / cancel."""
from flask import Blueprint

import clock
import db
import domain
import response
from auth import require_roles
from errors import ApiError
from routes.common import (check_incident_read_scope, load_incident,
                           load_work_order)
from validate import get_body, opt_str, req_str

bp = Blueprint("workorders", __name__)

ALL = ("SystemAdmin", "Dispatcher", "FieldTechnician", "Supervisor", "Regulator")


@bp.route("/gas-ops/repair-work-orders/<workOrderId>", methods=["GET"])
@require_roles(*ALL)
def get_work_order(workOrderId, user_id, role):
    wo = load_work_order(workOrderId)
    incident = load_incident(wo["incident_id"])
    check_incident_read_scope(incident, role, user_id)
    return response.success(domain.ser_work_order(wo), 200)


def _load(wo_id):
    wo = load_work_order(wo_id)
    incident = load_incident(wo["incident_id"])
    return wo, incident


@bp.route("/gas-ops/repair-work-orders/<workOrderId>/schedule", methods=["POST"])
@require_roles("Supervisor")
def schedule(workOrderId, user_id, role):
    wo, incident = _load(workOrderId)
    body = get_body()
    crew_id = req_str(body, "crew_id")
    window_start = clock.parse_dt(body.get("window_start"))
    window_end = clock.parse_dt(body.get("window_end"))
    if window_end <= window_start:
        raise ApiError("ERR_INVALID_TIME_RANGE",
                       "window_end must be strictly after window_start", 400)
    crew = db.crews.get(crew_id)
    if crew is None:
        raise ApiError("ERR_CREW_NOT_FOUND", "Repair crew not found", 404)
    if wo["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Schedule requires an OPEN work order", 409)
    if not crew["is_active"]:
        raise ApiError("ERR_INVALID_STATE", "Crew is inactive", 409)
    if crew["territory_id"] != incident["territory_id"]:
        raise ApiError("ERR_INVALID_STATE",
                       "Crew territory differs from the incident territory", 409)
    # Travel buffer: a >= 30 minute gap against every other non-cancelled crew window.
    for other in db.work_orders.values():
        if other["id"] == wo["id"] or other["crew_id"] != crew_id:
            continue
        if other["status"] == "CANCELLED" or other["scheduled_window_start"] is None:
            continue
        if not (window_start >= other["scheduled_window_end"] + domain.TRAVEL_BUFFER
                or window_end <= other["scheduled_window_start"] - domain.TRAVEL_BUFFER):
            raise ApiError("ERR_TRAVEL_BUFFER_VIOLATION",
                           "Crew requires at least 30 minutes between scheduled windows", 409)
    if domain.final_determination(incident["id"]) is None:
        raise ApiError("ERR_DETERMINATION_REQUIRED",
                       "A FINAL responsibility determination is required to schedule", 422)
    territory = db.territories[incident["territory_id"]]
    if (domain.territory_reserved_cents(territory["id"]) + wo["current_estimate_cents"]
            > territory["repair_budget_cap_cents"]):
        raise ApiError("ERR_REPAIR_BUDGET_EXCEEDED",
                       "Scheduling would exceed the territory repair budget cap", 402)
    wo["crew_id"] = crew_id
    wo["scheduled_window_start"] = window_start
    wo["scheduled_window_end"] = window_end
    wo["status"] = "SCHEDULED"
    domain.bump(wo)
    return response.success(domain.ser_work_order(wo), 200)


@bp.route("/gas-ops/repair-work-orders/<workOrderId>/start", methods=["POST"])
@require_roles("Supervisor")
def start(workOrderId, user_id, role):
    wo, _ = _load(workOrderId)
    if wo["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Start requires a SCHEDULED work order", 409)
    wo["status"] = "IN_PROGRESS"
    domain.bump(wo)
    return response.success(domain.ser_work_order(wo), 200)


@bp.route("/gas-ops/repair-work-orders/<workOrderId>/hold", methods=["POST"])
@require_roles("Supervisor")
def hold(workOrderId, user_id, role):
    wo, _ = _load(workOrderId)
    opt_str(get_body(), "reason")
    if wo["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Hold requires an IN_PROGRESS work order", 409)
    wo["status"] = "ON_HOLD"
    domain.bump(wo)
    return response.success(domain.ser_work_order(wo), 200)


@bp.route("/gas-ops/repair-work-orders/<workOrderId>/resume", methods=["POST"])
@require_roles("Supervisor")
def resume(workOrderId, user_id, role):
    wo, _ = _load(workOrderId)
    if wo["status"] != "ON_HOLD":
        raise ApiError("ERR_INVALID_STATE", "Resume requires an ON_HOLD work order", 409)
    wo["status"] = "IN_PROGRESS"
    domain.bump(wo)
    return response.success(domain.ser_work_order(wo), 200)


@bp.route("/gas-ops/repair-work-orders/<workOrderId>/complete", methods=["POST"])
@require_roles("Supervisor")
def complete(workOrderId, user_id, role):
    wo, incident = _load(workOrderId)
    body = get_body()
    lines = body.get("lines")
    if not isinstance(lines, list) or not lines:
        raise ApiError("ERR_INVALID_REQUEST", "lines must be a non-empty array", 400)
    for line in lines:
        if not isinstance(line, dict):
            raise ApiError("ERR_INVALID_REQUEST", "each line must be an object", 400)
        if not isinstance(line.get("description"), str):
            raise ApiError("ERR_INVALID_REQUEST", "line.description must be a string", 400)
        qty = line.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, (int, float)):
            raise ApiError("ERR_INVALID_REQUEST", "line.quantity must be a number", 400)
        price = line.get("unit_price_cents")
        if isinstance(price, bool) or not isinstance(price, int):
            raise ApiError("ERR_INVALID_REQUEST", "line.unit_price_cents must be an integer", 400)
        disc = line.get("discount_pct")
        if isinstance(disc, bool) or not isinstance(disc, (int, float)):
            raise ApiError("ERR_INVALID_REQUEST", "line.discount_pct must be a number", 400)
        if disc < 0 or disc >= 1:
            raise ApiError("ERR_INVALID_REQUEST", "line.discount_pct must be in [0, 1)", 400)
    labor_minutes = body.get("labor_minutes")
    if isinstance(labor_minutes, bool) or not isinstance(labor_minutes, int):
        raise ApiError("ERR_INVALID_REQUEST", "labor_minutes must be an integer", 400)
    if labor_minutes < 0:
        raise ApiError("ERR_INVALID_REQUEST", "labor_minutes must be >= 0", 400)
    if wo["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Complete requires an IN_PROGRESS work order", 409)
    crew = db.crews[wo["crew_id"]]
    parts_total, labor_billed, labor_cost, final_cost = domain.compute_final_cost(
        lines, labor_minutes, crew["hourly_rate_cents"])
    wo["lines"] = lines
    wo["labor_minutes"] = labor_minutes
    wo["labor_billed_minutes"] = labor_billed
    wo["final_cost_cents"] = final_cost
    wo["current_estimate_cents"] = final_cost
    wo["completed_at"] = clock.now()
    wo["status"] = "COMPLETED"
    domain.bump(wo)
    return response.success(domain.ser_work_order(wo), 200)


@bp.route("/gas-ops/repair-work-orders/<workOrderId>/cancel", methods=["POST"])
@require_roles("Supervisor")
def cancel(workOrderId, user_id, role):
    wo, _ = _load(workOrderId)
    reason = opt_str(get_body(), "reason")
    if wo["status"] not in ("OPEN", "SCHEDULED", "ON_HOLD"):
        raise ApiError("ERR_INVALID_STATE",
                       "Cancel requires an OPEN, SCHEDULED, or ON_HOLD work order", 409)
    wo["cancel_reason"] = reason
    wo["status"] = "CANCELLED"
    domain.bump(wo)
    return response.success(domain.ser_work_order(wo), 200)
