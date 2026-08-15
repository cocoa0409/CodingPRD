"""Delivery trips: schedule, list, read, start, complete, fail, reschedule."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles, forbid
from response import ok, created, paginate
from services import calc, domain
from validation import validate_body

bp = Blueprint("trips", __name__)

WINDOW_SCHEMA = {
    "planned_start_utc": ("datetime", True),
    "planned_end_utc": ("datetime", True),
}


def _load_trip(tid):
    trip = store.trips.get(tid)
    if trip is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Delivery trip not found")
    return trip


def _check_driver(trip, uid):
    if uid != trip["driver_id"]:
        forbid("Caller is not the driver assigned to this trip")


def _parse_window(body):
    start = db.parse_datetime(body["planned_start_utc"])
    end = db.parse_datetime(body["planned_end_utc"])
    if not end > start:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "planned_end_utc must be strictly later than planned_start_utc")
    return start, end


@bp.post("/delivery-trips")
def create_trip():
    uid, role = get_context()
    require_roles(["RentalCoordinator"])
    schema = {
        "contract_id": ("string", True),
        "line_id": ("string", True),
        "trip_type": ("enum", True, {"values": ["DELIVERY", "PICKUP"]}),
        "driver_id": ("string", True),
    }
    schema.update(WINDOW_SCHEMA)
    body = validate_body(schema)
    start, end = _parse_window(body)
    contract = store.contracts.get(body["contract_id"])
    if contract is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Rental contract not found")
    line = store.lines.get(body["line_id"])
    if line is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Rental line not found")
    if line["contract_id"] != contract["id"]:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "line_id does not belong to the given contract")
    if domain.route_window_conflict(body["driver_id"], start, end):
        raise ApiError("ERR_ROUTE_WINDOW_CONFLICT", 409,
                       "Window intersects the buffered window of another trip for this driver")
    trip = db.new_common({
        "id": db.new_id(),
        "contract_id": contract["id"],
        "line_id": line["id"],
        "trip_type": body["trip_type"],
        "status": "SCHEDULED",
        "driver_id": body["driver_id"],
        "planned_start_utc": body["planned_start_utc"],
        "planned_end_utc": body["planned_end_utc"],
        "standby_minutes": 0,
        "standby_charge_cents": 0,
        "crew_labor_hours": 0,
        "labor_charge_cents": 0,
        "trip_fee_cents": calc.TRIP_FEE_CENTS,
        "failure_reason": None,
        "completed_at": None,
    })
    store.trips[trip["id"]] = trip
    return created(domain.view_trip(trip))


@bp.get("/delivery-trips")
def list_trips():
    uid, role = get_context()
    require_roles(["BranchManager", "RentalCoordinator", "Driver"])
    rows = list(store.trips.values())
    for f in ("contract_id", "line_id", "driver_id", "status"):
        rows = paginate.filter(rows, f)
    rows = [domain.view_trip(t) for t in rows]
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/delivery-trips/<tid>")
def get_trip(tid):
    uid, role = get_context()
    require_roles(["BranchManager", "RentalCoordinator", "Driver"])
    trip = _load_trip(tid)
    return ok(domain.view_trip(trip))


@bp.post("/delivery-trips/<tid>/start")
def start_trip(tid):
    uid, role = get_context()
    require_roles(["Driver"])
    trip = _load_trip(tid)
    _check_driver(trip, uid)
    if trip["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Trip is not SCHEDULED")
    trip["status"] = "EN_ROUTE"
    db.touch(trip)
    return ok(domain.view_trip(trip))


@bp.post("/delivery-trips/<tid>/complete")
def complete_trip(tid):
    uid, role = get_context()
    require_roles(["Driver"])
    trip = _load_trip(tid)
    _check_driver(trip, uid)
    body = validate_body({
        "standby_minutes": ("integer", False, {"min": 0, "default": 0}),
        "crew_labor_hours": ("number", False, {"min": 0, "default": 0}),
    })
    if trip["status"] != "EN_ROUTE":
        raise ApiError("ERR_INVALID_STATE", 409, "Trip is not EN_ROUTE")
    line = store.lines[trip["line_id"]]
    contract = store.contracts[trip["contract_id"]]
    unit = store.units[line["unit_id"]]
    cls = store.classes[line["class_id"]]
    if trip["trip_type"] == "DELIVERY":
        if line["status"] != "RESERVED":
            raise ApiError("ERR_INVALID_STATE", 409, "Line is not RESERVED")
        if contract["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Contract is not ACTIVE")
        if not domain.unit_rentable(unit):
            raise ApiError("ERR_UNIT_NOT_RENTABLE", 422,
                           "Unit is not AVAILABLE or its inspection is overdue")
    else:  # PICKUP
        if line["status"] != "OFF_RENT":
            raise ApiError("ERR_INVALID_STATE", 409, "Line is not OFF_RENT")
    # Charge components: flat fee, standby beyond 30 free minutes, scaffold labor.
    trip["standby_minutes"] = body["standby_minutes"]
    trip["crew_labor_hours"] = body["crew_labor_hours"]
    trip["standby_charge_cents"] = calc.standby_charge_cents(body["standby_minutes"])
    trip["labor_charge_cents"] = calc.labor_charge_cents(
        cls["category"], body["crew_labor_hours"])
    trip["trip_fee_cents"] = calc.TRIP_FEE_CENTS
    trip["completed_at"] = db.logical_stamp()
    trip["status"] = "COMPLETED"
    db.touch(trip)
    customer = store.customers.get(contract["customer_id"])
    if trip["trip_type"] == "DELIVERY":
        line["status"] = "OUT_ON_RENT"
        line["on_rent_at"] = db.logical_stamp()
        db.touch(line)
        unit["status"] = "ON_RENT"
        db.touch(unit)
        db.touch(contract)  # logistics_subtotal_cents recompute
    else:  # PICKUP
        line["status"] = "RETURNED"
        line["final_charge_cents"] = line["accrued_charge_cents"]
        db.touch(line)
        due = db.parse_date(domain.next_inspection_due(unit["last_annual_inspection_date"]))
        unit["status"] = "AVAILABLE" if db.logical_date() <= due else "QUARANTINED"
        db.touch(unit)
        db.touch(contract)  # rental_subtotal recompute (line RETURNED cascade)
        db.touch(contract)  # logistics_subtotal recompute (trip completion)
    if customer is not None:
        calc.maybe_suspend(customer)
    return ok(domain.view_trip(trip))


@bp.post("/delivery-trips/<tid>/fail")
def fail_trip(tid):
    uid, role = get_context()
    require_roles(["Driver"])
    trip = _load_trip(tid)
    _check_driver(trip, uid)
    body = validate_body({"failure_reason": ("string", True)})
    if trip["status"] != "EN_ROUTE":
        raise ApiError("ERR_INVALID_STATE", 409, "Trip is not EN_ROUTE")
    trip["failure_reason"] = body["failure_reason"]
    trip["status"] = "FAILED"
    db.touch(trip)
    return ok(domain.view_trip(trip))


@bp.post("/delivery-trips/<tid>/reschedule")
def reschedule_trip(tid):
    uid, role = get_context()
    require_roles(["RentalCoordinator"])
    trip = _load_trip(tid)
    body = validate_body(dict(WINDOW_SCHEMA))
    start, end = _parse_window(body)
    if trip["status"] != "FAILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Trip is not FAILED")
    if domain.route_window_conflict(trip["driver_id"], start, end):
        raise ApiError("ERR_ROUTE_WINDOW_CONFLICT", 409,
                       "Window intersects the buffered window of another trip for this driver")
    trip["planned_start_utc"] = body["planned_start_utc"]
    trip["planned_end_utc"] = body["planned_end_utc"]
    trip["status"] = "SCHEDULED"
    db.touch(trip)
    return ok(domain.view_trip(trip))
