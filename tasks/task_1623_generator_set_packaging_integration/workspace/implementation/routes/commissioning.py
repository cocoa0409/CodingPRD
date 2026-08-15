"""CommissioningEvent endpoints."""

from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp

bp = Blueprint("commissioning", __name__)

MAX_EVENTS_PER_ENGINEER_PER_DAY = 2


@bp.route("/genset-packaging/commissioning-events", methods=["POST"])
def create_commissioning_event():
    mw.require_roles("FieldServiceManager")
    body = mw.get_json_body()

    order_id = mw.require_string(body, "order_id")
    shipment_id = mw.require_string(body, "shipment_id")
    service_date = mw.require_string(body, "service_date")

    order = db.orders.get(order_id)
    if order is None:
        raise errors.not_found("Package order not found")
    shipment = db.shipments.get(shipment_id)
    if shipment is None:
        raise errors.not_found("Shipment not found")

    # Gate: order build_status must be DELIVERED
    if order["build_status"] != "DELIVERED":
        raise errors.ApiError(
            errors.ERR_INVALID_BUILD_STATE, 409,
            "Order build_status must be DELIVERED to request commissioning",
        )

    record = {
        "order_id": order_id,
        "shipment_id": shipment_id,
        "service_date": service_date,
        "assigned_engineer_id": None,
        "training_hours": None,
        "checklist_completed": None,
        "status": "REQUESTED",
    }
    db.stamp_new(record)
    db.commissioning_events[record["id"]] = record
    return resp.success_created(record)


@bp.route("/genset-packaging/commissioning-events/<eventId>", methods=["GET"])
def get_commissioning_event(eventId):
    mw.authenticate()
    record = db.commissioning_events.get(eventId)
    if record is None:
        raise errors.not_found("Commissioning event not found")
    return resp.success_object(record)


@bp.route("/genset-packaging/commissioning-events", methods=["GET"])
def list_commissioning_events():
    mw.authenticate()
    limit, offset = mw.parse_pagination()

    items = list(db.commissioning_events.values())
    for param in ("order_id", "shipment_id"):
        val = mw.request.args.get(param)
        if val:
            items = [e for e in items if e.get(param) == val]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.success_list(page, limit, offset, total)


@bp.route("/genset-packaging/commissioning-events/<eventId>/assign", methods=["POST"])
def assign_engineer(eventId):
    mw.require_roles("FieldServiceManager")
    body = mw.get_json_body()

    event = db.commissioning_events.get(eventId)
    if event is None:
        raise errors.not_found("Commissioning event not found")

    if event["status"] not in ("REQUESTED", "ASSIGNED"):
        raise errors.ApiError(
            errors.ERR_EVENT_STATE_INVALID, 409,
            "Event must be REQUESTED or ASSIGNED to assign an engineer",
        )

    engineer_id = mw.require_string(body, "engineer_id")

    # Capacity check: count of this engineer's events on the same service_date
    # with status ASSIGNED, IN_PROGRESS, or COMPLETED must be < 2.
    # When reassigning, exclude this event itself from the count.
    day_load = sum(
        1 for e in db.commissioning_events.values()
        if e["assigned_engineer_id"] == engineer_id
        and e["service_date"] == event["service_date"]
        and e["status"] in ("ASSIGNED", "IN_PROGRESS", "COMPLETED")
        and e["id"] != event["id"]
    )
    if day_load >= MAX_EVENTS_PER_ENGINEER_PER_DAY:
        raise errors.ApiError(
            errors.ERR_ENGINEER_DAY_CAPACITY_EXCEEDED, 409,
            "Engineer already has 2 active commissioning events on that service_date",
        )

    event["assigned_engineer_id"] = engineer_id
    event["status"] = "ASSIGNED"
    db.touch(event)
    return resp.success_object(event)


@bp.route("/genset-packaging/commissioning-events/<eventId>/start", methods=["POST"])
def start_commissioning(eventId):
    mw.require_roles("FieldServiceManager")

    event = db.commissioning_events.get(eventId)
    if event is None:
        raise errors.not_found("Commissioning event not found")

    if event["status"] != "ASSIGNED":
        raise errors.ApiError(
            errors.ERR_EVENT_STATE_INVALID, 409,
            "Event must be ASSIGNED to start",
        )

    event["status"] = "IN_PROGRESS"
    db.touch(event)
    return resp.success_object(event)


@bp.route("/genset-packaging/commissioning-events/<eventId>/complete", methods=["POST"])
def complete_commissioning(eventId):
    mw.require_roles("FieldServiceManager")
    body = mw.get_json_body()

    event = db.commissioning_events.get(eventId)
    if event is None:
        raise errors.not_found("Commissioning event not found")

    if event["status"] != "IN_PROGRESS":
        raise errors.ApiError(
            errors.ERR_EVENT_STATE_INVALID, 409,
            "Event must be IN_PROGRESS to complete",
        )

    training_hours = mw.require_number(body, "training_hours")
    checklist_completed = mw.require_field(body, "checklist_completed")
    if not isinstance(checklist_completed, bool):
        raise errors.invalid_request("checklist_completed must be a boolean")

    # Gate: linked shipment must be DELIVERED
    shipment = db.shipments.get(event["shipment_id"])
    if shipment is None:
        raise errors.not_found("Shipment not found")
    if shipment["status"] != "DELIVERED":
        raise errors.ApiError(
            errors.ERR_SHIPMENT_NOT_DELIVERED, 409,
            "Linked shipment must be DELIVERED to complete commissioning",
        )

    # Gate: checklist and training hours
    if not checklist_completed:
        raise errors.ApiError(
            errors.ERR_TRAINING_INCOMPLETE, 422,
            "checklist_completed must be true",
        )
    if training_hours < 2.0:
        raise errors.ApiError(
            errors.ERR_TRAINING_INCOMPLETE, 422,
            "training_hours must be >= 2.0",
        )

    event["training_hours"] = training_hours
    event["checklist_completed"] = checklist_completed
    event["status"] = "COMPLETED"
    db.touch(event)
    return resp.success_object(event)


@bp.route("/genset-packaging/commissioning-events/<eventId>/accept", methods=["POST"])
def accept_commissioning(eventId):
    user_id, role = mw.require_roles("CustomerContact")

    event = db.commissioning_events.get(eventId)
    if event is None:
        raise errors.not_found("Commissioning event not found")

    if event["status"] != "COMPLETED":
        raise errors.ApiError(
            errors.ERR_EVENT_STATE_INVALID, 409,
            "Event must be COMPLETED to accept",
        )

    # Ownership: X-User-ID must equal order.customer_id
    order = db.orders.get(event["order_id"])
    if order is None:
        raise errors.not_found("Package order not found")
    if user_id != order["customer_id"]:
        raise errors.forbidden(
            "CustomerContact may only accept commissioning for their own account"
        )

    event["status"] = "ACCEPTED"
    db.touch(event)

    # Order build: DELIVERED -> COMMISSIONED; commercial INVOICED -> CLOSED
    if order["build_status"] == "DELIVERED":
        order["build_status"] = "COMMISSIONED"
        db.touch(order)
    if order["commercial_status"] == "INVOICED":
        order["commercial_status"] = "CLOSED"
        db.touch(order)
        # PRD §3.1: credit_utilized_cents tracks, exactly and at all times, the
        # sum of committed_amount_cents over orders that are AUTHORIZED or
        # INVOICED — this order has just left that set.
        customer = db.customers.get(order["customer_id"])
        if customer is not None:
            customer["credit_utilized_cents"] -= order["committed_amount_cents"]
            db.touch(customer)

    return resp.success_object(event)
