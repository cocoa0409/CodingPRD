"""Procurement orders, staging reservations and outage windows."""

from flask import Blueprint

import calc
import serialize
from db import db, fmt_dt, new_row, ordered, touch
from errors import ApiError
from middleware import (
    endpoint,
    enforce_scope,
    project_of_car,
    project_of_option,
    project_of_order,
    project_of_reservation,
    project_of_window,
    touch_project,
)
from routes.common import (
    ALL_ROLES,
    enum_query,
    eq_filter,
    fetch,
    object_response,
    paged,
    read_one,
    require,
    str_query,
)
from validation import bad, precheck_fks, validate

bp = Blueprint("delivery", __name__)

ITEM_TYPES = ["CONTROLLER", "MACHINE", "DOOR_OPERATOR", "POWER_UNIT"]
ORDER_STATUSES = ["DRAFT", "ORDERED", "STAGED", "INSTALLED", "CANCELLED"]
RESERVATION_STATUSES = ["HELD", "RELEASED"]
SERVICE_PLANS = ["STAIRS_ONLY", "ADJACENT_CAR", "ATTENDANT_SERVICE"]
WINDOW_STATUSES = ["PLANNED", "ACTIVE", "COMPLETED", "CANCELLED"]


def _reservations_of_order(order_id):
    return ordered(
        [r for r in db.staging_reservations.values() if r["procurement_order_id"] == order_id]
    )


def _release(reservation):
    reservation["status"] = "RELEASED"
    reservation["released_at"] = db.clock_str
    reservation["_released_at"] = db.clock_dt
    touch(reservation)


# --- ProcurementOrder ------------------------------------------------------

@bp.post("/procurement-orders")
@endpoint(["ProjectManager"])
def create_order():
    precheck_fks([("scope_option_id", db.scope_options)])
    data = validate(
        [
            {"name": "scope_option_id", "type": "id", "required": True},
            {"name": "item_type", "type": "enum", "required": True, "values": ITEM_TYPES},
            {"name": "lead_time_days", "type": "int", "required": True},
            {"name": "required_staging_sqft", "type": "int", "required": True},
        ]
    )
    option = require(db.scope_options.get(data["scope_option_id"]))
    project = project_of_option(option)
    row = new_row(
        ordered_at=None,
        promised_delivery_date=None,
        staging_reservation_id=None,
        status="DRAFT",
        **data
    )
    db.procurement_orders[row["id"]] = row
    if option["status"] in ("DRAFT", "SUBMITTED"):
        calc.recompute_pricing(option)
        touch(option)
    touch_project(project)
    return object_response(serialize.procurement_order(row), 201)


@bp.get("/procurement-orders/<procurement_order_id>")
@endpoint(ALL_ROLES)
def get_order(procurement_order_id):
    row = fetch(db.procurement_orders, procurement_order_id)
    return read_one(row, serialize.procurement_order, project_of_order(row))


@bp.get("/procurement-orders")
@endpoint(ALL_ROLES)
def list_orders():
    scope_option_id = str_query("scope_option_id")
    status = enum_query("status", ORDER_STATUSES)
    item_type = enum_query("item_type", ITEM_TYPES)
    rows = eq_filter(list(db.procurement_orders.values()), "scope_option_id", scope_option_id)
    rows = eq_filter(rows, "status", status)
    rows = eq_filter(rows, "item_type", item_type)
    return paged(rows, serialize.procurement_order, project_of_order)


def _order_context(order_id):
    order = fetch(db.procurement_orders, order_id)
    option = db.scope_options.get(order["scope_option_id"])
    project = project_of_option(option)
    enforce_scope(project)
    return order, option, project


@bp.post("/procurement-orders/<procurement_order_id>/issue")
@endpoint(["ProjectManager"])
def issue_order(procurement_order_id):
    order, option, project = _order_context(procurement_order_id)
    validate([])
    if order["status"] != "DRAFT":
        raise ApiError("ERR_PROCUREMENT_STATE_INVALID")
    if option["status"] != "APPROVED":
        raise ApiError("ERR_SCOPE_OPTION_NOT_APPROVED")
    if calc.downtime_posture(project) == "FROZEN":
        raise ApiError("ERR_PROJECT_FROZEN")
    order["status"] = "ORDERED"
    order["ordered_at"] = db.clock_str
    order["_ordered_at"] = db.clock_dt
    promised = calc.add_days(db.clock_dt, order["lead_time_days"])
    order["promised_delivery_date"] = fmt_dt(promised)
    order["_promised_delivery_date"] = promised
    touch(order)
    touch_project(project)
    return object_response(serialize.procurement_order(order))


@bp.post("/procurement-orders/<procurement_order_id>/receive")
@endpoint(["ProjectManager", "ServiceManager"])
def receive_order(procurement_order_id):
    order, _option, project = _order_context(procurement_order_id)
    precheck_fks([("staging_reservation_id", db.staging_reservations)])
    data = validate([{"name": "staging_reservation_id", "type": "id", "required": True}])
    reservation = require(db.staging_reservations.get(data["staging_reservation_id"]))
    if order["status"] != "ORDERED":
        raise ApiError("ERR_PROCUREMENT_STATE_INVALID")
    if reservation["status"] != "HELD":
        raise ApiError("ERR_RESERVATION_STATE_INVALID")
    if reservation["procurement_order_id"] != order["id"]:
        raise ApiError("ERR_RESERVATION_ORDER_MISMATCH")
    order["status"] = "STAGED"
    order["staging_reservation_id"] = reservation["id"]
    touch(order)
    touch_project(project)
    return object_response(serialize.procurement_order(order))


@bp.post("/procurement-orders/<procurement_order_id>/install")
@endpoint(["ProjectManager", "ServiceManager"])
def install_order(procurement_order_id):
    order, _option, project = _order_context(procurement_order_id)
    validate([])
    if order["status"] != "STAGED":
        raise ApiError("ERR_PROCUREMENT_STATE_INVALID")
    if calc.downtime_posture(project) == "FROZEN":
        raise ApiError("ERR_PROJECT_FROZEN")
    order["status"] = "INSTALLED"
    touch(order)
    for reservation in _reservations_of_order(order["id"]):
        if reservation["status"] == "HELD":
            _release(reservation)
    touch_project(project)
    return object_response(serialize.procurement_order(order))


@bp.post("/procurement-orders/<procurement_order_id>/cancel")
@endpoint(["ProjectManager"])
def cancel_order(procurement_order_id):
    order, option, project = _order_context(procurement_order_id)
    validate([])
    if order["status"] not in ("DRAFT", "ORDERED", "STAGED"):
        raise ApiError("ERR_PROCUREMENT_STATE_INVALID")
    order["status"] = "CANCELLED"
    touch(order)
    for reservation in _reservations_of_order(order["id"]):
        if reservation["status"] == "HELD":
            _release(reservation)
    if option is not None and option["status"] in ("DRAFT", "SUBMITTED"):
        calc.recompute_pricing(option)
        touch(option)
    touch_project(project)
    return object_response(serialize.procurement_order(order))


# --- StagingReservation ----------------------------------------------------

@bp.post("/staging-reservations")
@endpoint(["ProjectManager", "ServiceManager"])
def create_reservation():
    precheck_fks([("procurement_order_id", db.procurement_orders)])
    data = validate(
        [
            {"name": "procurement_order_id", "type": "id", "required": True},
            {"name": "sqft", "type": "int", "required": True, "min": 1},
            {"name": "hold_start", "type": "datetime", "required": True},
            {"name": "hold_end", "type": "datetime", "required": True},
            {"name": "expected_project_version", "type": "int", "required": True},
        ]
    )
    order = require(db.procurement_orders.get(data["procurement_order_id"]))
    hold_start = data["hold_start"]["dt"]
    hold_end = data["hold_end"]["dt"]
    if hold_end <= hold_start:
        raise bad("hold_end must be strictly after hold_start.")
    project = project_of_order(order)
    enforce_scope(project)
    if project["version"] != data["expected_project_version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION")
    if calc.downtime_posture(project) == "FROZEN":
        raise ApiError("ERR_PROJECT_FROZEN")
    peak = calc.staging_peak_sqft(project["id"], hold_start, hold_end)
    if peak + data["sqft"] > project["staging_area_sqft"]:
        raise ApiError("ERR_STAGING_CAPACITY_EXCEEDED")

    row = new_row(
        procurement_order_id=data["procurement_order_id"],
        sqft=data["sqft"],
        hold_start=data["hold_start"]["raw"],
        hold_end=data["hold_end"]["raw"],
        status="HELD",
        released_at=None,
    )
    row["_hold_start"] = hold_start
    row["_hold_end"] = hold_end
    row["_released_at"] = None
    db.staging_reservations[row["id"]] = row
    touch_project(project)
    return object_response(serialize.staging_reservation(row), 201)


@bp.get("/staging-reservations/<staging_reservation_id>")
@endpoint(ALL_ROLES)
def get_reservation(staging_reservation_id):
    row = fetch(db.staging_reservations, staging_reservation_id)
    return read_one(row, serialize.staging_reservation, project_of_reservation(row))


@bp.get("/staging-reservations")
@endpoint(ALL_ROLES)
def list_reservations():
    order_id = str_query("procurement_order_id")
    status = enum_query("status", RESERVATION_STATUSES)
    rows = eq_filter(list(db.staging_reservations.values()), "procurement_order_id", order_id)
    rows = eq_filter(rows, "status", status)
    return paged(rows, serialize.staging_reservation, project_of_reservation)


@bp.post("/staging-reservations/<staging_reservation_id>/release")
@endpoint(["ProjectManager", "ServiceManager"])
def release_reservation(staging_reservation_id):
    reservation = fetch(db.staging_reservations, staging_reservation_id)
    project = project_of_reservation(reservation)
    enforce_scope(project)
    validate([])
    if reservation["status"] != "HELD":
        raise ApiError("ERR_RESERVATION_STATE_INVALID")
    _release(reservation)
    touch_project(project)
    return object_response(serialize.staging_reservation(reservation))


# --- OutageWindow ----------------------------------------------------------

@bp.post("/outage-windows")
@endpoint(["ProjectManager"])
def create_window():
    precheck_fks([("car_id", db.cars), ("predecessor_window_id", db.outage_windows)])
    data = validate(
        [
            {"name": "car_id", "type": "id", "required": True},
            {"name": "start_at", "type": "datetime", "required": True},
            {"name": "end_at", "type": "datetime", "required": True},
            {
                "name": "temporary_service_plan",
                "type": "enum",
                "required": True,
                "values": SERVICE_PLANS,
            },
            {"name": "predecessor_window_id", "type": "id"},
        ]
    )
    car = require(db.cars.get(data["car_id"]))
    predecessor = None
    if data["predecessor_window_id"] is not None:
        predecessor = require(db.outage_windows.get(data["predecessor_window_id"]))
    start_at = data["start_at"]["dt"]
    end_at = data["end_at"]["dt"]
    if end_at <= start_at:
        raise bad("end_at must be strictly after start_at.")
    project = project_of_car(car)
    if project["status"] == "COMPLETED":
        raise ApiError("ERR_PROJECT_STATE_INVALID")
    if predecessor is not None:
        pred_car = db.cars.get(predecessor["car_id"])
        if pred_car is None or pred_car["group_id"] != car["group_id"]:
            raise ApiError("ERR_CAR_GROUP_MISMATCH")
    if project["occupancy_type"] == "OCCUPIED" and data["temporary_service_plan"] == "STAIRS_ONLY":
        raise ApiError("ERR_TEMP_SERVICE_PLAN_INADEQUATE")
    if predecessor is not None and start_at < predecessor["_end_at"]:
        raise ApiError("ERR_PREDECESSOR_NOT_COMPLETE")
    if calc.outage_buffer_conflict(project, car["group_id"], start_at, end_at):
        raise ApiError("ERR_OUTAGE_BUFFER_CONFLICT")

    row = new_row(
        car_id=data["car_id"],
        predecessor_window_id=data["predecessor_window_id"],
        start_at=data["start_at"]["raw"],
        end_at=data["end_at"]["raw"],
        extension_hours=0,
        temporary_service_plan=data["temporary_service_plan"],
        advance_notice_sent_at=None,
        notice_count=0,
        notice_lead_hours=None,
        status="PLANNED",
        activated_at=None,
        completed_at=None,
    )
    row["_start_at"] = start_at
    row["_end_at"] = end_at
    row["_advance_notice_sent_at"] = None
    row["_activated_at"] = None
    row["_completed_at"] = None
    db.outage_windows[row["id"]] = row
    return object_response(serialize.outage_window(row), 201)


@bp.get("/outage-windows/<outage_window_id>")
@endpoint(ALL_ROLES)
def get_window(outage_window_id):
    row = fetch(db.outage_windows, outage_window_id)
    return read_one(row, serialize.outage_window, project_of_window(row))


@bp.get("/outage-windows")
@endpoint(ALL_ROLES)
def list_windows():
    car_id = str_query("car_id")
    predecessor_window_id = str_query("predecessor_window_id")
    status = enum_query("status", WINDOW_STATUSES)
    rows = eq_filter(list(db.outage_windows.values()), "car_id", car_id)
    rows = eq_filter(rows, "predecessor_window_id", predecessor_window_id)
    rows = eq_filter(rows, "status", status)
    return paged(rows, serialize.outage_window, project_of_window)


def _window_context(window_id):
    window = fetch(db.outage_windows, window_id)
    car = db.cars.get(window["car_id"])
    project = project_of_car(car)
    enforce_scope(project)
    return window, car, project


@bp.post("/outage-windows/<outage_window_id>/send-notice")
@endpoint(["ProjectManager", "BuildingRepresentative"])
def send_notice(outage_window_id):
    window, _car, _project = _window_context(outage_window_id)
    validate([])
    if window["advance_notice_sent_at"] is None:
        window["advance_notice_sent_at"] = db.clock_str
        window["_advance_notice_sent_at"] = db.clock_dt
        window["notice_lead_hours"] = calc.hours_between(db.clock_dt, window["_start_at"])
    window["notice_count"] += 1
    touch(window)
    return object_response(serialize.outage_window(window))


@bp.post("/outage-windows/<outage_window_id>/activate")
@endpoint(["ProjectManager", "ServiceManager"])
def activate_window(outage_window_id):
    window, car, project = _window_context(outage_window_id)
    validate([])
    if window["status"] != "PLANNED":
        raise ApiError("ERR_OUTAGE_STATE_INVALID")
    group = db.groups.get(car["group_id"])
    in_service_after = calc.group_cars_in_service(group)
    if car["work_status"] != "OUTAGE_ACTIVE":
        in_service_after -= 1
    if in_service_after < group["min_cars_in_service"]:
        raise ApiError("ERR_GROUP_SERVICE_FLOOR")
    if project["occupancy_type"] != "VACANT":
        if (
            calc.downtime_posture(project) == "RESTRICTED"
            and window["temporary_service_plan"] == "STAIRS_ONLY"
        ):
            raise ApiError("ERR_TEMP_SERVICE_PLAN_INADEQUATE")
    if window["predecessor_window_id"] is not None:
        predecessor = db.outage_windows.get(window["predecessor_window_id"])
        if predecessor is None or predecessor["status"] != "COMPLETED":
            raise ApiError("ERR_PREDECESSOR_NOT_COMPLETE")
    if calc.outage_buffer_conflict(
        project, car["group_id"], window["_start_at"], window["_end_at"], window["id"]
    ):
        raise ApiError("ERR_OUTAGE_BUFFER_CONFLICT")
    if window["advance_notice_sent_at"] is None or window["notice_lead_hours"] is None:
        raise ApiError("ERR_TENANT_NOTICE_LEAD_UNMET")
    if window["notice_lead_hours"] < calc.Decimal(project["tenant_notice_lead_hours"]):
        raise ApiError("ERR_TENANT_NOTICE_LEAD_UNMET")
    if db.clock_dt >= window["_end_at"]:
        raise ApiError("ERR_WINDOW_EXPIRED")
    if calc.project_active_outage_count(project) >= project["max_concurrent_outages"]:
        raise ApiError("ERR_CONCURRENCY_CAP_EXCEEDED")
    if calc.downtime_posture(project) == "FROZEN":
        raise ApiError("ERR_PROJECT_FROZEN")

    window["status"] = "ACTIVE"
    window["activated_at"] = db.clock_str
    window["_activated_at"] = db.clock_dt
    touch(window)
    if car["work_status"] == "PROCURING":
        car["work_status"] = "OUTAGE_ACTIVE"
        touch(car)
    touch_project(project)
    return object_response(serialize.outage_window(window))


@bp.post("/outage-windows/<outage_window_id>/complete")
@endpoint(["ProjectManager", "ServiceManager"])
def complete_window(outage_window_id):
    window, _car, project = _window_context(outage_window_id)
    validate([])
    if window["status"] != "ACTIVE":
        raise ApiError("ERR_OUTAGE_STATE_INVALID")
    window["status"] = "COMPLETED"
    window["completed_at"] = db.clock_str
    window["_completed_at"] = db.clock_dt
    touch(window)
    # The project's active_outage_count and downtime_posture are refreshed, so
    # the project row is itself mutated (PRD 3.7, PRD 2.8).
    touch_project(project)
    return object_response(serialize.outage_window(window))


@bp.post("/outage-windows/<outage_window_id>/cancel")
@endpoint(["ProjectManager"])
def cancel_window(outage_window_id):
    window, _car, _project = _window_context(outage_window_id)
    validate([])
    if window["status"] != "PLANNED":
        raise ApiError("ERR_OUTAGE_STATE_INVALID")
    window["status"] = "CANCELLED"
    touch(window)
    return object_response(serialize.outage_window(window))
