"""Pickup routes, appointments and disposition assignments."""
from datetime import timedelta

from flask import Blueprint

from db import base_record, db, now, ordered, paginate, touch
from errors import api_error, invalid
from middleware import require
from response import collection, single
from serialize import (DISPOSITION_ASSIGNMENT, PICKUP_APPOINTMENT,
                       PICKUP_ROUTE, dump, dump_many)
from services import calc, entities, orders as order_service
from util import date_of, whole_days
from validate import Fields, Query

bp = Blueprint("logistics", __name__)

ROUTE_STATUSES = ("DRAFT", "PUBLISHED")
APPOINTMENT_STATUSES = ("BOOKED", "COMPLETED", "MISSED", "CANCELLED")
APPOINTMENT_OUTCOMES = ("COMPLETED", "MISSED")
ASSIGNMENT_STATUSES = ("ASSIGNED", "DELIVERED", "REJECTED")
ASSIGNMENT_OUTCOMES = ("DELIVERED", "REJECTED")
OCCUPYING = ("BOOKED", "COMPLETED")


@bp.route("/pickup-routes", methods=["POST"])
@require("LogisticsCoordinator")
def create_pickup_route():
    fields = Fields("region_code", "route_date", "window_start_at",
                    "window_end_at", "capacity_units", "buffer_minutes")
    region_code = fields.string("region_code")
    route_date = fields.date("route_date")
    window_start_at = fields.timestamp("window_start_at")
    window_end_at = fields.timestamp("window_end_at")
    capacity_units = fields.integer("capacity_units", minimum=1)
    buffer_minutes = fields.integer("buffer_minutes", required=False,
                                    default=30, minimum=0)
    if window_end_at <= window_start_at:
        raise invalid("window_end_at must be after window_start_at")
    record = base_record()
    record.update({
        "region_code": region_code,
        "route_date": route_date,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "buffer_minutes": buffer_minutes,
        "capacity_units": capacity_units,
        "booked_units": 0,
        "available_units": capacity_units,
        "status": "DRAFT",
    })
    db.pickup_routes[record["id"]] = record
    return single(dump(record, PICKUP_ROUTE), 201)


@bp.route("/pickup-routes/<route_id>", methods=["GET"])
@require("LogisticsCoordinator", "PlatformAdmin")
def read_pickup_route(route_id):
    route = entities.get_route(route_id)
    entities.refresh_route_capacity(route)
    return single(dump(route, PICKUP_ROUTE), 200)


@bp.route("/pickup-routes/<route_id>/publish", methods=["POST"])
@require("LogisticsCoordinator")
def publish_pickup_route(route_id):
    Fields()
    route = entities.get_route(route_id)
    if route["status"] != "DRAFT":
        raise api_error("ERR_ROUTE_NOT_PUBLISHED",
                        "Only a DRAFT route can be published")
    route["status"] = "PUBLISHED"
    touch(route)
    return single(dump(route, PICKUP_ROUTE), 200)


@bp.route("/pickup-appointments", methods=["POST"])
@require("LogisticsCoordinator")
def create_pickup_appointment():
    fields = Fields("route_id", "return_case_id", "slot_start_at",
                    "slot_end_at", "expected_pickup_route_version")
    route_id = fields.reference("route_id")
    return_case_id = fields.reference("return_case_id")
    slot_start_at = fields.timestamp("slot_start_at")
    slot_end_at = fields.timestamp("slot_end_at")
    expected_version = fields.integer("expected_pickup_route_version")
    if slot_end_at <= slot_start_at:
        raise invalid("slot_end_at must be after slot_start_at")

    route = entities.get_route(route_id)
    case = entities.get_return_case(return_case_id)
    if case["logistics_status"] != "REQUESTED":
        raise api_error("ERR_INVALID_RETURN_STATE",
                        "Only a REQUESTED return case can be scheduled")
    if route["status"] != "PUBLISHED":
        raise api_error("ERR_ROUTE_NOT_PUBLISHED",
                        "Appointments may only be booked on a PUBLISHED route")
    if expected_version != route["version"]:
        raise api_error("ERR_STALE_ROUTE_VERSION",
                        "expected_pickup_route_version does not match the "
                        "route's current version")

    if (slot_start_at < route["window_start_at"]
            or slot_end_at > route["window_end_at"]
            or date_of(slot_start_at) != route["route_date"]
            or date_of(slot_end_at) != route["route_date"]):
        raise api_error("ERR_SLOT_OUTSIDE_ROUTE_WINDOW",
                        "The slot must sit inside the route's window on the "
                        "route date")

    buffer = timedelta(minutes=route["buffer_minutes"])
    for other in entities.appointments_of_route(route["id"]):
        if other["status"] not in OCCUPYING:
            continue
        separated = (slot_start_at >= other["slot_end_at"] + buffer
                     or slot_end_at + buffer <= other["slot_start_at"])
        if not separated:
            raise api_error("ERR_SLOT_OVERLAP",
                            "The slot does not clear the route's buffer from "
                            "an existing appointment")

    order = entities.get_order(case["order_id"])
    model = entities.model_of_order(order)
    units = calc.units_for_size(model["size"])
    entities.refresh_route_capacity(route)
    if route["booked_units"] + units > route["capacity_units"]:
        raise api_error("ERR_ROUTE_CAPACITY_EXCEEDED",
                        "The route does not have %d free units" % units)

    appointment = base_record()
    appointment.update({
        "route_id": route["id"],
        "return_case_id": case["id"],
        "slot_start_at": slot_start_at,
        "slot_end_at": slot_end_at,
        "units": units,
        "status": "BOOKED",
        "closed_at": None,
    })
    db.pickup_appointments[appointment["id"]] = appointment
    entities.refresh_route_capacity(route)
    touch(route)
    case["logistics_status"] = "PICKUP_SCHEDULED"
    touch(case)
    return single(dump(appointment, PICKUP_APPOINTMENT), 201)


@bp.route("/pickup-appointments/<appointment_id>", methods=["GET"])
@require("LogisticsCoordinator", "PlatformAdmin")
def read_pickup_appointment(appointment_id):
    appointment = entities.get_appointment(appointment_id)
    return single(dump(appointment, PICKUP_APPOINTMENT), 200)


@bp.route("/pickup-appointments", methods=["GET"])
@require("LogisticsCoordinator", "PlatformAdmin")
def list_pickup_appointments():
    query = Query("route_id", "return_case_id", "status")
    limit, offset = query.page()
    route_id = query.string("route_id")
    return_case_id = query.string("return_case_id")
    status = query.enum("status", APPOINTMENT_STATUSES)
    matches = ordered([
        a for a in db.pickup_appointments.values()
        if (route_id is None or a["route_id"] == route_id)
        and (return_case_id is None or a["return_case_id"] == return_case_id)
        and (status is None or a["status"] == status)
    ])
    page, total = paginate(matches, limit, offset)
    return collection(dump_many(page, PICKUP_APPOINTMENT), limit, offset,
                      total)


@bp.route("/pickup-appointments/<appointment_id>/complete", methods=["POST"])
@require("LogisticsCoordinator")
def complete_pickup_appointment(appointment_id):
    fields = Fields("outcome")
    outcome = fields.enum("outcome", APPOINTMENT_OUTCOMES)
    appointment = entities.get_appointment(appointment_id)
    if appointment["status"] != "BOOKED":
        raise api_error("ERR_INVALID_APPOINTMENT_STATE",
                        "Only a BOOKED appointment can be closed out")
    clock = now()
    route = db.pickup_routes.get(appointment["route_id"])
    case = entities.get_return_case(appointment["return_case_id"])

    if outcome == "MISSED":
        appointment["status"] = "MISSED"
        appointment["closed_at"] = clock
        touch(appointment)
        if route is not None:
            entities.refresh_route_capacity(route)
            touch(route)
        case["logistics_status"] = "REQUESTED"
        touch(case)
        return single(dump(appointment, PICKUP_APPOINTMENT), 200)

    appointment["status"] = "COMPLETED"
    appointment["closed_at"] = clock
    touch(appointment)
    if route is not None:
        entities.refresh_route_capacity(route)
        touch(route)

    order = entities.get_order(case["order_id"])
    nights_used = max(0, whole_days(order["delivered_at"], clock) or 0)
    case["logistics_status"] = "PICKED_UP"
    case["picked_up_at"] = clock
    case["nights_used"] = nights_used
    touch(case)

    order["trial_status"] = "RETURNED"
    if order["fulfillment_status"] in ("DELIVERED", "DAMAGED_REPORTED"):
        order["fulfillment_status"] = "CLOSED"
    order_service.freeze_nights(order, nights_used)
    touch(order)

    customer = entities.get_customer(order["customer_id"])
    prior_returns = customer["completed_return_count"]
    customer["completed_return_count"] = prior_returns + 1
    if prior_returns >= 1:
        entities.add_signal(customer, "REPEAT_RETURN")
    if nights_used < calc.SHORT_TRIAL_NIGHTS:
        entities.add_signal(customer, "SHORT_TRIAL")
    entities.derive_customer(customer)
    touch(customer)
    return single(dump(appointment, PICKUP_APPOINTMENT), 200)


@bp.route("/pickup-appointments/<appointment_id>/cancel", methods=["POST"])
@require("LogisticsCoordinator")
def cancel_pickup_appointment(appointment_id):
    Fields()
    appointment = entities.get_appointment(appointment_id)
    if appointment["status"] != "BOOKED":
        raise api_error("ERR_INVALID_APPOINTMENT_STATE",
                        "Only a BOOKED appointment can be cancelled")
    appointment["status"] = "CANCELLED"
    touch(appointment)
    route = db.pickup_routes.get(appointment["route_id"])
    if route is not None:
        entities.refresh_route_capacity(route)
        touch(route)
    case = entities.get_return_case(appointment["return_case_id"])
    if case["logistics_status"] == "PICKUP_SCHEDULED":
        case["logistics_status"] = "REQUESTED"
        touch(case)
    return single(dump(appointment, PICKUP_APPOINTMENT), 200)


@bp.route("/disposition-assignments/<assignment_id>", methods=["GET"])
@require("LogisticsCoordinator", "FinanceController", "PlatformAdmin")
def read_disposition_assignment(assignment_id):
    assignment = entities.get_assignment(assignment_id)
    return single(dump(assignment, DISPOSITION_ASSIGNMENT), 200)


@bp.route("/disposition-assignments", methods=["GET"])
@require("LogisticsCoordinator", "FinanceController", "PlatformAdmin")
def list_disposition_assignments():
    query = Query("return_case_id", "partner_id", "intake_date", "status")
    limit, offset = query.page()
    return_case_id = query.string("return_case_id")
    partner_id = query.string("partner_id")
    intake_date = query.date("intake_date")
    status = query.enum("status", ASSIGNMENT_STATUSES)
    matches = ordered([
        a for a in db.disposition_assignments.values()
        if (return_case_id is None or a["return_case_id"] == return_case_id)
        and (partner_id is None or a["partner_id"] == partner_id)
        and (intake_date is None or a["intake_date"] == intake_date)
        and (status is None or a["status"] == status)
    ])
    page, total = paginate(matches, limit, offset)
    return collection(dump_many(page, DISPOSITION_ASSIGNMENT), limit, offset,
                      total)


@bp.route("/disposition-assignments/<assignment_id>/confirm-intake",
          methods=["POST"])
@require("LogisticsCoordinator")
def confirm_intake(assignment_id):
    fields = Fields("outcome")
    outcome = fields.enum("outcome", ASSIGNMENT_OUTCOMES)
    assignment = entities.get_assignment(assignment_id)
    if assignment["status"] != "ASSIGNED":
        raise api_error("ERR_INVALID_ASSIGNMENT_STATE",
                        "Only an ASSIGNED disposition can be confirmed")
    if outcome == "DELIVERED":
        assignment["status"] = "DELIVERED"
        touch(assignment)
        return single(dump(assignment, DISPOSITION_ASSIGNMENT), 200)

    assignment["status"] = "REJECTED"
    touch(assignment)
    case = entities.get_return_case(assignment["return_case_id"])
    if case["logistics_status"] == "DISPOSITIONED":
        case["logistics_status"] = "INSPECTED"
        case["disposition"] = "PENDING"
        touch(case)
    return single(dump(assignment, DISPOSITION_ASSIGNMENT), 200)
