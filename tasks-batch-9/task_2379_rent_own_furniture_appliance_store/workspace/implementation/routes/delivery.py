"""Delivery orders: crew windows, failed attempts and the start of billing."""

from datetime import timedelta

from flask import Blueprint

import clock
import middleware
import response
import validators
from db import base_row, db, public, sort_rows, touch
from errors import ApiError
from routes import common
from services import calc, domain

bp = Blueprint("delivery", __name__)

SERVICE_TYPES = ("DELIVERY_ONLY", "DELIVERY_SETUP")
FAIL_REASONS = ("CUSTOMER_ABSENT", "ACCESS_BLOCKED", "VEHICLE_ISSUE")
MAX_ATTEMPTS = 3


def _conflicts(crew_id, agreement_id, start, end):
    """Half-open intervals with the buffer on the existing order's tail only."""
    buffer_ = timedelta(minutes=calc.CREW_TRAVEL_BUFFER_MINUTES)
    for order in sort_rows(db.delivery_orders.values(), "window_start_at"):
        if order["crew_id"] != crew_id or order["agreement_id"] == agreement_id:
            continue
        if order["status"] != "SCHEDULED":
            continue
        other_start = clock.parse(order["window_start_at"])
        other_end = clock.parse(order["window_end_at"])
        if other_start is None or other_end is None:
            continue
        if start < other_end + buffer_ and end > other_start:
            return True
    return False


@bp.post("/agreements/<agreement_id>/delivery-orders")
def create_delivery_order(agreement_id):
    middleware.authenticate((middleware.PLATFORM_ADMIN, middleware.STORE_MANAGER))
    agreement = domain.require_agreement(agreement_id)
    body = validators.json_body()
    crew_id = validators.identifier(body, "crew_id")
    service_type = validators.enum(body, "service_type", SERVICE_TYPES)
    start = validators.datetime_field(body, "window_start_at")
    end = validators.datetime_field(body, "window_end_at")
    expected = validators.integer(body, "expected_agreement_version")

    crew = domain.require_crew(crew_id)
    domain.check_expected_version(agreement, expected)
    domain.check_payment_status(agreement, domain.OP_DELIVERY_CREATE)

    if crew["store_id"] != agreement["store_id"]:
        raise ApiError("ERR_CREW_STORE_MISMATCH")
    if crew["status"] != "ACTIVE":
        raise ApiError("ERR_CREW_INACTIVE")
    unit = db.units.get(agreement["unit_id"])
    if (
        unit is not None
        and unit["category"] == "APPLIANCE"
        and service_type == "DELIVERY_SETUP"
        and not crew["setup_certified"]
    ):
        raise ApiError("ERR_CREW_NOT_SETUP_CERTIFIED")
    if end <= start:
        raise ApiError("ERR_INVALID_WINDOW")
    if _conflicts(crew["id"], agreement["id"], start, end):
        raise ApiError("ERR_CREW_WINDOW_CONFLICT")

    # the create is also a reschedule: the agreement's own live order steps aside
    for order in sort_rows(
        domain.agreement_delivery_orders(agreement["id"]), "window_start_at"
    ):
        if order["status"] in ("SCHEDULED", "FAILED_ATTEMPT"):
            order["status"] = "SUPERSEDED"
            touch(order)

    order = base_row()
    order["agreement_id"] = agreement["id"]
    order["crew_id"] = crew["id"]
    order["service_type"] = service_type
    order["window_start_at"] = clock.fmt(start)
    order["window_end_at"] = clock.fmt(end)
    order["status"] = "SCHEDULED"
    order["attempt_count"] = 0
    order["setup_completed"] = False
    order["completed_at"] = None
    db.delivery_orders[order["id"]] = order

    touch(agreement)
    return response.object_response(public(order), 201)


@bp.get("/delivery-orders/<order_id>")
def read_delivery_order(order_id):
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.COMPLIANCE_OFFICER,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
            middleware.SERVICE_TECHNICIAN,
        )
    )
    order = domain.require_delivery_order(order_id)
    return response.object_response(public(order))


@bp.get("/delivery-orders")
def list_delivery_orders():
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.COMPLIANCE_OFFICER,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
            middleware.SERVICE_TECHNICIAN,
        )
    )
    return common.paged(
        list(db.delivery_orders.values()),
        primary="window_start_at",
        filters=("agreement_id", "crew_id", "status"),
    )


@bp.post("/delivery-orders/<order_id>/complete")
def complete_delivery(order_id):
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.STORE_MANAGER,
            middleware.SERVICE_TECHNICIAN,
        )
    )
    order = domain.require_delivery_order(order_id)
    body = validators.json_body()
    setup_completed = validators.boolean(body, "setup_completed")

    agreement = db.agreements.get(order["agreement_id"])
    domain.check_possession_status(agreement, domain.OP_DELIVERY_COMPLETE)
    unit = db.units.get(agreement["unit_id"])
    if unit is None or unit["status"] != "RESERVED":
        raise ApiError("ERR_UNIT_NOT_AVAILABLE")
    if order["status"] != "SCHEDULED":
        raise ApiError("ERR_DELIVERY_ORDER_STATE_INVALID")
    if unit["category"] == "APPLIANCE" and not setup_completed:
        raise ApiError("ERR_SETUP_NOT_COMPLETED")

    now = clock.now()
    order["status"] = "COMPLETED"
    order["setup_completed"] = setup_completed
    order["completed_at"] = clock.fmt(now)
    touch(order)

    agreement["possession_status"] = "DELIVERED"
    agreement["cycle_anchor_at"] = clock.fmt(now)
    domain.sync_agreement_money(agreement)
    touch(agreement)

    unit["status"] = "ON_RENT"
    touch(unit)
    store = db.stores.get(unit["store_id"])
    if store is not None:
        domain.sync_store(store)
    return response.object_response(public(order))


@bp.post("/delivery-orders/<order_id>/fail-attempt")
def fail_delivery_attempt(order_id):
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.STORE_MANAGER,
            middleware.SERVICE_TECHNICIAN,
        )
    )
    order = domain.require_delivery_order(order_id)
    body = validators.json_body()
    validators.enum(body, "reason", FAIL_REASONS)

    if order["status"] != "SCHEDULED":
        raise ApiError("ERR_DELIVERY_ORDER_STATE_INVALID")

    order["attempt_count"] += 1
    if order["attempt_count"] >= MAX_ATTEMPTS:
        order["status"] = "FAILED_ATTEMPT"
        agreement = db.agreements.get(order["agreement_id"])
        unit = db.units.get(agreement["unit_id"]) if agreement else None
        if unit is not None and unit["status"] == "RESERVED":
            unit["status"] = "AVAILABLE"
            touch(unit)
            store = db.stores.get(unit["store_id"])
            if store is not None:
                domain.sync_store(store)
    touch(order)
    return response.object_response(public(order))
