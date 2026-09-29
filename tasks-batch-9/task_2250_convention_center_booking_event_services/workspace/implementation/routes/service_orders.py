"""Event services ordering across utilities, rigging, cleaning, security (PRD 3.5)."""

from flask import Blueprint

import calc
import clock
import lookups
import validate
from db import db
from errors import err
from middleware import body, endpoint, filter_rows, touch
from response import entity_response
from routes.common import (
    SERVICE_CATEGORIES,
    body_fk,
    listing,
    require_coi_current,
    require_posture,
)
from util import parse_date

bp = Blueprint("service_orders", __name__)


@bp.post("/bookings/<booking_id>/service-orders")
@endpoint("EventServicesManager")
def create_service_order(booking_id):
    booking = lookups.fetch("booking", booking_id)
    payload = body()

    # ladder step 5 then step 7
    vendor = body_fk(payload, "vendor_id", "vendor")
    service_category = validate.req_enum(payload, "service_category", SERVICE_CATEGORIES)
    quantity = validate.req_number(payload, "ordered_quantity", exclusive_min=0)

    # ladder step 10 then the eligibility gates of step 14, in the PRD's order
    require_posture(booking)
    require_coi_current(vendor)
    space = db.spaces.get(booking["space_id"])
    if service_category == "RIGGING" and not (space and space.get("rigging_capable")):
        raise err("ERR_SPACE_NOT_RIGGING_CAPABLE")
    if vendor["service_category"] != service_category:
        raise err("ERR_VENDOR_CATEGORY_MISMATCH")
    exclusive = [
        v
        for v in db.vendors.rows()
        if v["service_category"] == service_category and v["vendor_tier"] == "EXCLUSIVE"
    ]
    if exclusive and vendor["id"] not in [v["id"] for v in exclusive]:
        raise err("ERR_EXCLUSIVE_VENDOR_REQUIRED")

    order = db.insert(
        "service_order",
        {
            "booking_id": booking["id"],
            "vendor_id": vendor["id"],
            "service_category": service_category,
            "ordered_quantity": quantity,
            "order_timing": calc.order_timing(
                clock.today(), parse_date(booking["show_start_date"])
            ),
            "approval_status": "PENDING_APPROVAL",
            "billing_status": "UNBILLED",
            "estimated_charge_cents": 0,
            "actual_quantity": None,
            "actual_charge_cents": None,
        },
    )
    return entity_response(order, 201)


@bp.get("/service-orders")
@endpoint("VenueAdmin", "EventServicesManager", "SettlementAnalyst")
def list_service_orders():
    rows = filter_rows(
        "service_order",
        {
            "booking_id": "booking_id",
            "vendor_id": "vendor_id",
            "approval_status": "approval_status",
            "billing_status": "billing_status",
        },
    )
    return listing(rows)


@bp.get("/service-orders/<order_id>")
@endpoint("VenueAdmin", "EventServicesManager", "SettlementAnalyst")
def read_service_order(order_id):
    return entity_response(lookups.fetch("service_order", order_id))


@bp.post("/service-orders/<order_id>/approve")
@endpoint("EventServicesManager")
def approve_service_order(order_id):
    order = lookups.fetch("service_order", order_id)
    if order["approval_status"] != "PENDING_APPROVAL":
        raise err("ERR_SERVICE_ORDER_STATE_INVALID")
    booking = db.bookings.get(order["booking_id"])
    require_posture(booking)
    vendor = db.vendors.get(order["vendor_id"])
    require_coi_current(vendor)

    order["approval_status"] = "APPROVED"
    order["billing_status"] = "ESTIMATED"
    order["estimated_charge_cents"] = calc.service_order_charge(
        order, vendor, order["ordered_quantity"]
    )
    touch(order)
    return entity_response(order)


@bp.post("/service-orders/<order_id>/reject")
@endpoint("EventServicesManager")
def reject_service_order(order_id):
    order = lookups.fetch("service_order", order_id)
    if order["approval_status"] != "PENDING_APPROVAL":
        raise err("ERR_SERVICE_ORDER_STATE_INVALID")
    order["approval_status"] = "REJECTED"
    order["billing_status"] = "VOID"
    touch(order)
    return entity_response(order)


@bp.post("/service-orders/<order_id>/cancel")
@endpoint("EventServicesManager")
def cancel_service_order(order_id):
    order = lookups.fetch("service_order", order_id)
    if order["approval_status"] not in ("PENDING_APPROVAL", "APPROVED"):
        raise err("ERR_SERVICE_ORDER_STATE_INVALID")
    if order["approval_status"] == "APPROVED" and order["billing_status"] == "RECONCILED":
        raise err("ERR_SERVICE_ORDER_STATE_INVALID")

    if order["billing_status"] == "ESTIMATED":
        order["estimated_charge_cents"] = 0
    order["approval_status"] = "CANCELLED"
    order["billing_status"] = "VOID"
    touch(order)
    return entity_response(order)


@bp.post("/service-orders/<order_id>/reconcile")
@endpoint("EventServicesManager")
def reconcile_service_order(order_id):
    order = lookups.fetch("service_order", order_id)
    payload = body()
    actual = validate.req_number(payload, "actual_quantity", exclusive_min=0)

    if order["approval_status"] != "APPROVED" or order["billing_status"] != "ESTIMATED":
        raise err("ERR_SERVICE_ORDER_STATE_INVALID")
    booking = db.bookings.get(order["booking_id"])
    if booking is None or booking["status"] != "IN_HOUSE":
        raise err("ERR_BOOKING_STATE_INVALID")
    require_posture(booking, allowed=("OPEN", "RESTRICTED"))

    vendor = db.vendors.get(order["vendor_id"])
    order["actual_quantity"] = actual
    order["actual_charge_cents"] = calc.service_order_charge(order, vendor, actual)
    order["billing_status"] = "RECONCILED"
    touch(order)
    return entity_response(order)
