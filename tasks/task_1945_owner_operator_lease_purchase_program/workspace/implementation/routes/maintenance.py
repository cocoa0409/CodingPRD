"""ServiceBay and MaintenanceWorkOrder routes."""

from datetime import timedelta

from flask import Blueprint, request

import clock
import errors
import middleware
from db import db
from response import success
from services.core import base_entity, touch, BAY_BUFFER_HOURS
from services.serialize import serialize_bay, serialize_work_order
from util import (
    get_body, req_str, req_int, req_enum, req_dt,
    parse_pagination, paginate,
)

bp = Blueprint("maintenance", __name__)

CATEGORIES = {"PREVENTIVE", "REPAIR", "RECALL"}


# ---- ServiceBay ----

@bp.post("/service-bays")
def create_bay():
    middleware.require_roles({"MaintenanceCoordinator"})
    body = get_body()
    bay_code = req_str(body, "bay_code")
    location = req_str(body, "location")
    for b in db.service_bays.values():
        if b["bay_code"] == bay_code:
            raise errors.err(errors.ERR_DUPLICATE_VALUE, "bay_code must be unique", 409)
    bay = base_entity()
    bay.update({"bay_code": bay_code, "location": location})
    db.service_bays[bay["id"]] = bay
    return success(serialize_bay(bay), "object", 201)


@bp.get("/service-bays/<bay_id>")
def get_bay(bay_id):
    middleware.require_roles(middleware.ALL_ROLES)
    bay = db.service_bays.get(bay_id)
    if bay is None:
        raise errors.err(errors.ERR_BAY_NOT_FOUND, "ServiceBay not found", 404)
    return success(serialize_bay(bay), "object", 200)


# ---- MaintenanceWorkOrder ----

def _get_wo_or_404(wo_id):
    wo = db.maintenance_work_orders.get(wo_id)
    if wo is None:
        raise errors.err(errors.ERR_WORK_ORDER_NOT_FOUND, "MaintenanceWorkOrder not found", 404)
    return wo


@bp.post("/maintenance-work-orders")
def create_work_order():
    middleware.require_roles({"MaintenanceCoordinator"})
    body = get_body()
    lease_id = req_str(body, "lease_id")
    service_bay_id = req_str(body, "service_bay_id")
    category = req_enum(body, "category", CATEGORIES)
    description = req_str(body, "description")
    scheduled_start = req_dt(body, "scheduled_start")
    scheduled_end = req_dt(body, "scheduled_end")
    estimated_cost_cents = req_int(body, "estimated_cost_cents")

    lease = db.lease_agreements.get(lease_id)
    if lease is None:
        raise errors.err(errors.ERR_LEASE_NOT_FOUND, "LeaseAgreement not found", 404)
    bay = db.service_bays.get(service_bay_id)
    if bay is None:
        raise errors.err(errors.ERR_BAY_NOT_FOUND, "ServiceBay not found", 404)

    if scheduled_end <= scheduled_start:
        raise errors.err(
            errors.ERR_INVALID_DATE_RANGE,
            "scheduled_end must be after scheduled_start",
            400,
        )
    if lease["status"] not in ("ACTIVE", "DEFAULTED"):
        raise errors.err(errors.ERR_LEASE_NOT_ACTIVE, "Lease must be ACTIVE or DEFAULTED", 409)

    buffer = timedelta(hours=BAY_BUFFER_HOURS)
    for other in db.maintenance_work_orders.values():
        if (
            other["service_bay_id"] == service_bay_id
            and other["status"] in ("OPEN", "COMPLETED")
        ):
            gap_ok = (
                scheduled_start >= other["_scheduled_end"] + buffer
                or scheduled_end <= other["_scheduled_start"] - buffer
            )
            if not gap_ok:
                raise errors.err(
                    errors.ERR_BAY_WINDOW_CONFLICT,
                    "Bay booking conflicts with an existing booking (2-hour buffer)",
                    409,
                )

    wo = base_entity()
    wo.update({
        "lease_id": lease_id,
        "service_bay_id": service_bay_id,
        "category": category,
        "description": description,
        "_scheduled_start": scheduled_start,
        "_scheduled_end": scheduled_end,
        "estimated_cost_cents": estimated_cost_cents,
        "actual_cost_cents": None,
        "odometer_at_service": None,
        "_completed_at": None,
        "billed_to": None,
        "status": "OPEN",
    })
    db.maintenance_work_orders[wo["id"]] = wo
    return success(serialize_work_order(wo), "object", 201)


@bp.get("/maintenance-work-orders")
def list_work_orders():
    middleware.require_roles(middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.maintenance_work_orders.values())
    lease_filter = request.args.get("lease_id")
    bay_filter = request.args.get("service_bay_id")
    status_filter = request.args.get("status")
    if lease_filter is not None:
        items = [w for w in items if w["lease_id"] == lease_filter]
    if bay_filter is not None:
        items = [w for w in items if w["service_bay_id"] == bay_filter]
    if status_filter is not None:
        items = [w for w in items if w["status"] == status_filter]
    items.sort(key=lambda w: (w["created_at"], w["id"]))
    page, pg = paginate(items, limit, offset)
    return success([serialize_work_order(w) for w in page], "array", 200, pagination=pg)


@bp.get("/maintenance-work-orders/<wo_id>")
def get_work_order(wo_id):
    middleware.require_roles(middleware.ALL_ROLES)
    return success(serialize_work_order(_get_wo_or_404(wo_id)), "object", 200)


@bp.post("/maintenance-work-orders/<wo_id>/complete")
def complete_work_order(wo_id):
    middleware.require_roles({"MaintenanceCoordinator"})
    wo = _get_wo_or_404(wo_id)
    body = get_body()
    actual_cost_cents = req_int(body, "actual_cost_cents")
    odometer_at_service = req_int(body, "odometer_at_service")
    if wo["status"] != "OPEN":
        raise errors.err(errors.ERR_WORK_ORDER_NOT_OPEN, "Work order is not OPEN", 409)

    lease = db.lease_agreements[wo["lease_id"]]
    truck = db.trucks[lease["truck_id"]]

    if wo["category"] == "RECALL":
        billed_to = "CARRIER"
    elif wo["category"] == "PREVENTIVE":
        billed_to = "OPERATOR"
    else:  # REPAIR
        if (
            odometer_at_service <= truck["powertrain_warranty_mileage_limit"]
            and wo["_scheduled_start"] <= truck["_warranty_expires_on"]
        ):
            billed_to = "WARRANTY"
        else:
            billed_to = "OPERATOR"

    wo["actual_cost_cents"] = actual_cost_cents
    wo["odometer_at_service"] = odometer_at_service
    wo["_completed_at"] = clock.now()
    wo["billed_to"] = billed_to
    wo["status"] = "COMPLETED"
    touch(wo)

    if odometer_at_service > truck["odometer_current"]:
        truck["odometer_current"] = odometer_at_service
        touch(truck)

    return success(serialize_work_order(wo), "object", 200)


@bp.post("/maintenance-work-orders/<wo_id>/cancel")
def cancel_work_order(wo_id):
    middleware.require_roles({"MaintenanceCoordinator"})
    wo = _get_wo_or_404(wo_id)
    if wo["status"] != "OPEN":
        raise errors.err(errors.ERR_WORK_ORDER_NOT_OPEN, "Work order is not OPEN", 409)
    wo["status"] = "CANCELLED"
    touch(wo)
    return success(serialize_work_order(wo), "object", 200)
