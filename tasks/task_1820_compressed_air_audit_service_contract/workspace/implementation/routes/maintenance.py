"""Dryer/filter maintenance schedules."""

from flask import Blueprint, request

from auth import require_roles, check_ownership
from domain import facility_watermark, recompute_facility_chain
from envelope import ok_object, ok_list
from errors import (
    conflict,
    invalid_request,
    invalid_state,
    not_found,
    unprocessable,
    ERR_DUPLICATE_SCHEDULE_COMPONENT,
    ERR_READING_EXCEEDS_LOGGED,
    ERR_RUN_HOURS_REGRESSION,
)
import store
from store import new_resource, touch
from util import body_or_empty, parse_pagination, public, req_date, req_int, req_str, sort_and_page

bp = Blueprint("maintenance", __name__)

ALL_ROLES = ["DealerAdmin", "EnergyEngineer", "ServiceTech", "ContractManager", "FacilityManager"]
COMPONENTS = ("DRYER", "FILTER")


def _get_or_404(schedule_id):
    sched = store.maintenance_schedules.get(schedule_id)
    if sched is None:
        raise not_found("MaintenanceSchedule not found")
    return sched


@bp.route("/maintenance-schedules", methods=["POST"])
def create_schedule():
    require_roles(["DealerAdmin", "ContractManager"])
    body = body_or_empty()
    facility_id = req_str(body, "facility_id")
    component = req_str(body, "component")
    interval = req_int(body, "interval_hours")
    if component not in COMPONENTS:
        raise invalid_request("component must be DRYER or FILTER")
    if interval <= 0:
        raise invalid_request("interval_hours must be greater than zero")

    if store.facilities.get(facility_id) is None:
        raise not_found("Facility not found")

    # (facility, component) unique among ACTIVE schedules
    if any(
        s["facility_id"] == facility_id and s["component"] == component and s["status"] == "ACTIVE"
        for s in store.maintenance_schedules.values()
    ):
        raise conflict(ERR_DUPLICATE_SCHEDULE_COMPONENT, "An ACTIVE schedule for this component already exists")

    anchor = facility_watermark(facility_id)
    sched = new_resource()
    sched.update(
        {
            "facility_id": facility_id,
            "component": component,
            "interval_hours": interval,
            "anchor_run_hours": anchor,
            "next_due_run_hours": anchor + interval,
            "is_delinquent": False,
            "status": "ACTIVE",
        }
    )
    store.maintenance_schedules[sched["id"]] = sched
    recompute_facility_chain(facility_id)
    return ok_object(public(sched), 201)


@bp.route("/maintenance-schedules", methods=["GET"])
def list_schedules():
    require_roles(ALL_ROLES)
    items = list(store.maintenance_schedules.values())
    facility_id = request.args.get("facility_id")
    component = request.args.get("component")
    status = request.args.get("status")
    if facility_id is not None:
        items = [s for s in items if s["facility_id"] == facility_id]
    if component is not None:
        items = [s for s in items if s["component"] == component]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    limit, offset = parse_pagination()
    page, total = sort_and_page(items, limit, offset)
    return ok_list([public(s) for s in page], limit, offset, total)


@bp.route("/maintenance-schedules/<maintenanceScheduleId>", methods=["GET"])
def get_schedule(maintenanceScheduleId):
    user_id, role = require_roles(ALL_ROLES)
    sched = _get_or_404(maintenanceScheduleId)
    check_ownership(user_id, role, sched["facility_id"])
    return ok_object(public(sched), 200)


@bp.route("/maintenance-schedules/<maintenanceScheduleId>/record-service", methods=["POST"])
def record_service(maintenanceScheduleId):
    require_roles(["ServiceTech"])
    sched = _get_or_404(maintenanceScheduleId)
    body = body_or_empty()
    req_date(body, "service_date")  # validated, not persisted (no such field)
    reading = req_int(body, "run_hours_reading")

    if sched["status"] != "ACTIVE":
        raise invalid_state("MaintenanceSchedule must be ACTIVE to record service")
    if reading < sched["anchor_run_hours"]:
        raise unprocessable(ERR_RUN_HOURS_REGRESSION, "run_hours_reading below the schedule anchor")
    if reading > facility_watermark(sched["facility_id"]):
        raise unprocessable(ERR_READING_EXCEEDS_LOGGED, "run_hours_reading exceeds the facility watermark")

    sched["anchor_run_hours"] = reading
    sched["next_due_run_hours"] = reading + sched["interval_hours"]
    touch(sched)
    recompute_facility_chain(sched["facility_id"])
    return ok_object(public(sched), 200)


@bp.route("/maintenance-schedules/<maintenanceScheduleId>/retire", methods=["POST"])
def retire(maintenanceScheduleId):
    require_roles(["ContractManager"])
    sched = _get_or_404(maintenanceScheduleId)
    if sched["status"] != "ACTIVE":
        raise invalid_state("MaintenanceSchedule must be ACTIVE to retire")
    sched["status"] = "RETIRED"
    touch(sched)
    recompute_facility_chain(sched["facility_id"])
    return ok_object(public(sched), 200)
