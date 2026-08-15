"""Breakdown event endpoints."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from services.helpers import (
    get_pagination, paginate, require_fields, get_str, get_int, touch,
)
from services.pricing import calc_breakdown_compensation
from services.serializers import breakdown_view

bp = Blueprint("breakdowns", __name__)


@bp.route("/api/v1/orders/<oid>/breakdowns", methods=["POST"])
def create_breakdown(oid):
    require_roles("DispatchManager", "PlatformAdmin")
    o = db.orders.get(oid)
    if o is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "order not found")

    payload = request.get_json(silent=True) or {}
    require_fields(payload, "vehicle_id", "driver_id", "location", "description")
    vehicle_id = get_str(payload, "vehicle_id", required=True)
    driver_id = get_str(payload, "driver_id", required=True)
    location = get_str(payload, "location", required=True)
    description = get_str(payload, "description", required=True)

    if db.vehicles.get(vehicle_id) is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "vehicle not found")
    if db.drivers.get(driver_id) is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "driver not found")

    bid = db.new_id()
    now = db.iso_now()
    b = {
        "id": bid,
        "order_id": oid,
        "vehicle_id": vehicle_id,
        "driver_id": driver_id,
        "location": location,
        "description": description,
        "status": "REPORTED",
        "replacement_vehicle_id": None,
        "replacement_driver_id": None,
        "delay_minutes": 0,
        "resolution_notes": None,
        "customer_compensation_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.breakdowns[bid] = b
    return success_object(breakdown_view(b), status=201)


@bp.route("/api/v1/orders/<oid>/breakdowns", methods=["GET"])
def list_order_breakdowns(oid):
    require_roles("DispatchManager", "PlatformAdmin")
    o = db.orders.get(oid)
    if o is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "order not found")
    limit, offset = get_pagination()
    status = request.args.get("status")
    items = sorted([b for b in db.breakdowns.values() if b.get("order_id") == oid], key=lambda x: x["created_at"])
    if status:
        items = [b for b in items if b.get("status") == status]
    page, total = paginate(items, limit, offset)
    return success_list([breakdown_view(b) for b in page], limit, offset, total)


@bp.route("/api/v1/breakdowns", methods=["GET"])
def list_all_breakdowns():
    require_roles("DispatchManager", "PlatformAdmin")
    limit, offset = get_pagination()
    status = request.args.get("status")
    order_id = request.args.get("order_id")
    vehicle_id = request.args.get("vehicle_id")
    driver_id = request.args.get("driver_id")
    replacement_vehicle_id = request.args.get("replacement_vehicle_id")
    replacement_driver_id = request.args.get("replacement_driver_id")

    items = sorted(db.breakdowns.values(), key=lambda x: x["created_at"])
    if status:
        items = [b for b in items if b.get("status") == status]
    if order_id:
        items = [b for b in items if b.get("order_id") == order_id]
    if vehicle_id:
        items = [b for b in items if b.get("vehicle_id") == vehicle_id]
    if driver_id:
        items = [b for b in items if b.get("driver_id") == driver_id]
    if replacement_vehicle_id:
        items = [b for b in items if b.get("replacement_vehicle_id") == replacement_vehicle_id]
    if replacement_driver_id:
        items = [b for b in items if b.get("replacement_driver_id") == replacement_driver_id]
    page, total = paginate(items, limit, offset)
    return success_list([breakdown_view(b) for b in page], limit, offset, total)


@bp.route("/api/v1/breakdowns/<bid>", methods=["GET"])
def get_breakdown(bid):
    require_roles("DispatchManager", "PlatformAdmin")
    b = db.breakdowns.get(bid)
    if b is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "breakdown not found")
    return success_object(breakdown_view(b))


@bp.route("/api/v1/breakdowns/<bid>/dispatch", methods=["POST"])
def dispatch_breakdown(bid):
    require_roles("DispatchManager")
    b = db.breakdowns.get(bid)
    if b is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "breakdown not found")
    if b["status"] != "REPORTED":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"breakdown is in state {b['status']}, cannot dispatch")

    payload = request.get_json(silent=True) or {}
    replacement_vehicle_id = payload.get("replacement_vehicle_id")
    replacement_driver_id = payload.get("replacement_driver_id")
    if not replacement_vehicle_id:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "replacement_vehicle_id is required")

    replacement_vehicle = db.vehicles.get(replacement_vehicle_id)
    if replacement_vehicle is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "replacement vehicle not found")
    replacement_driver = None
    if replacement_driver_id:
        replacement_driver = db.drivers.get(replacement_driver_id)
        if replacement_driver is None:
            raise errors.make_error(errors.ERR_NOT_FOUND, "replacement driver not found")

    # Get quote for eligibility checks
    o = db.orders.get(b["order_id"])
    if o is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "order not found")
    quote = db.quotes.get(o["quote_id"])
    if quote is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "quote not found")

    now = db.now_utc()

    # Replacement eligibility (priority 19)
    if replacement_vehicle.get("status") != "AVAILABLE":
        raise errors.make_error(errors.ERR_REPLACEMENT_INELIGIBLE, "replacement vehicle is not AVAILABLE")
    if replacement_vehicle.get("seating_capacity", 0) < quote.get("passenger_count", 0):
        raise errors.make_error(errors.ERR_REPLACEMENT_INELIGIBLE, "replacement vehicle capacity insufficient")
    if db.parse_iso(replacement_vehicle["dot_inspection_expiry"]) <= now:
        raise errors.make_error(errors.ERR_REPLACEMENT_INELIGIBLE, "replacement vehicle DOT inspection expired")
    if db.parse_iso(replacement_vehicle["insurance_expiry"]) <= now:
        raise errors.make_error(errors.ERR_REPLACEMENT_INELIGIBLE, "replacement vehicle insurance expired")
    if quote.get("ada_required") and not replacement_vehicle.get("ada_accessible"):
        raise errors.make_error(errors.ERR_REPLACEMENT_INELIGIBLE, "replacement vehicle does not have ADA lift")

    # Commit
    b["replacement_vehicle_id"] = replacement_vehicle_id
    replacement_vehicle["status"] = "ASSIGNED"
    touch(replacement_vehicle)

    if replacement_driver:
        b["replacement_driver_id"] = replacement_driver_id
        replacement_driver["status"] = "ON_DUTY_NOT_DRIVING"
        touch(replacement_driver)

    # Original vehicle -> IN_MAINTENANCE
    original_vehicle = db.vehicles.get(b["vehicle_id"])
    if original_vehicle:
        original_vehicle["status"] = "IN_MAINTENANCE"
        touch(original_vehicle)
        # Create REPAIR maintenance record
        mid = db.new_id()
        m = {
            "id": mid,
            "vehicle_id": original_vehicle["id"],
            "maintenance_type": "REPAIR",
            "status": "SCHEDULED",
            "scheduled_date": db.iso_now(),
            "completed_date": None,
            "odometer_at_service": original_vehicle.get("odometer_miles", 0),
            "description": f"Repair for breakdown {b['id']}: {b.get('description', '')}",
            "technician": "",
            "cost_cents": 0,
            "next_due_miles": None,
            "dot_inspection_passed": None,
            "defects_found": [],
            "created_at": db.iso_now(),
        }
        db.maintenance_records[mid] = m

    b["status"] = "DISPATCHED"
    touch(b)
    return success_object(breakdown_view(b))


@bp.route("/api/v1/breakdowns/<bid>/en-route", methods=["POST"])
def en_route_breakdown(bid):
    require_roles("DispatchManager")
    b = db.breakdowns.get(bid)
    if b is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "breakdown not found")
    if b["status"] != "DISPATCHED":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"breakdown is in state {b['status']}, cannot mark en route")
    b["status"] = "REPLACEMENT_EN_ROUTE"
    touch(b)
    return success_object(breakdown_view(b))


@bp.route("/api/v1/breakdowns/<bid>/complete-replacement", methods=["POST"])
def complete_replacement(bid):
    require_roles("DispatchManager")
    b = db.breakdowns.get(bid)
    if b is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "breakdown not found")
    if b["status"] != "REPLACEMENT_EN_ROUTE":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"breakdown is in state {b['status']}, cannot complete replacement")

    payload = request.get_json(silent=True) or {}
    delay_minutes = payload.get("delay_minutes")
    if delay_minutes is None or isinstance(delay_minutes, bool) or not isinstance(delay_minutes, int):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "delay_minutes is required and must be an integer")
    if delay_minutes < 0:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "delay_minutes must be >= 0")

    resolution_notes = payload.get("resolution_notes", "")

    o = db.orders.get(b["order_id"])
    quote = db.quotes.get(o["quote_id"]) if o else None

    b["delay_minutes"] = delay_minutes
    compensation = calc_breakdown_compensation(delay_minutes, quote.get("subtotal_cents", 0) if quote else 0, o.get("deposit_paid_cents", 0) if o else 0)
    b["customer_compensation_cents"] = compensation
    b["resolution_notes"] = resolution_notes

    # Update order
    if o:
        o["assigned_vehicle_id"] = b["replacement_vehicle_id"]
        if b.get("replacement_driver_id"):
            o["assigned_driver_id"] = b["replacement_driver_id"]
        touch(o)

    # Replacement vehicle -> IN_TRIP
    if b.get("replacement_vehicle_id"):
        rv = db.vehicles.get(b["replacement_vehicle_id"])
        if rv:
            rv["status"] = "IN_TRIP"
            touch(rv)
    if b.get("replacement_driver_id"):
        rd = db.drivers.get(b["replacement_driver_id"])
        if rd:
            rd["status"] = "ON_TRIP"
            touch(rd)

    b["status"] = "REPLACED"
    touch(b)
    return success_object(breakdown_view(b))


@bp.route("/api/v1/breakdowns/<bid>/resolve-in-place", methods=["POST"])
def resolve_in_place(bid):
    require_roles("DispatchManager")
    b = db.breakdowns.get(bid)
    if b is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "breakdown not found")
    if b["status"] != "REPORTED":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"breakdown is in state {b['status']}, cannot resolve in place")

    payload = request.get_json(silent=True) or {}
    delay_minutes = payload.get("delay_minutes")
    if delay_minutes is None or isinstance(delay_minutes, bool) or not isinstance(delay_minutes, int):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "delay_minutes is required and must be an integer")
    if delay_minutes < 0:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "delay_minutes must be >= 0")

    resolution_notes = payload.get("resolution_notes", "")

    o = db.orders.get(b["order_id"])
    quote = db.quotes.get(o["quote_id"]) if o else None

    b["delay_minutes"] = delay_minutes
    compensation = calc_breakdown_compensation(delay_minutes, quote.get("subtotal_cents", 0) if quote else 0, o.get("deposit_paid_cents", 0) if o else 0)
    b["customer_compensation_cents"] = compensation
    b["resolution_notes"] = resolution_notes

    if o:
        touch(o)

    b["status"] = "RESOLVED_IN_PLACE"
    touch(b)
    return success_object(breakdown_view(b))


@bp.route("/api/v1/breakdowns/<bid>/cancel-dispatch", methods=["POST"])
def cancel_dispatch(bid):
    require_roles("DispatchManager")
    b = db.breakdowns.get(bid)
    if b is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "breakdown not found")
    if b["status"] != "DISPATCHED":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"breakdown is in state {b['status']}, cannot cancel dispatch")

    if b.get("replacement_vehicle_id"):
        rv = db.vehicles.get(b["replacement_vehicle_id"])
        if rv:
            rv["status"] = "AVAILABLE"
            touch(rv)
    if b.get("replacement_driver_id"):
        rd = db.drivers.get(b["replacement_driver_id"])
        if rd:
            rd["status"] = "AVAILABLE"
            touch(rd)

    original = db.vehicles.get(b["vehicle_id"])
    if original:
        original["status"] = "IN_TRIP"
        touch(original)

    b["status"] = "CANCELLED"
    touch(b)
    return success_object(breakdown_view(b))
