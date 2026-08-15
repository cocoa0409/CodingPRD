"""TruckTrip endpoints: plan, list, depart/complete/cancel, QA review,
adjudicate (breach cascade), reconcile, generate-orders."""

from flask import Blueprint, request

from clock import now, parse_iso, format_iso_ms
from db import DB
from middleware import require_role, require_any
from util import (
    get_json_body, check_unknown_fields, require_fields, opt_int, opt_enum,
    opt_date_str, opt_iso_dt, base_fields, paginate, err, touch, apply_changes,
)
from response import success_object, success_list
from errors import (
    ERR_INVALID_REQUEST, ERR_ROUTE_NOT_FOUND, ERR_DRIVER_NOT_FOUND,
    ERR_TRIP_NOT_FOUND, ERR_OWNERSHIP_MISMATCH,
    ERR_ROUTE_NOT_ACTIVE, ERR_TRIP_NOT_PLANNED, ERR_TRIP_NOT_DEPARTED,
    ERR_TRIP_NOT_COMPLETED, ERR_TRIP_NOT_IN_QA_REVIEW,
    ERR_ORDER_NOT_CONFIRMABLE, ERR_ORDER_NOT_CANCELLABLE,
    ERR_ORDER_NOT_DELIVERABLE, ERR_COLD_CHAIN_PRECOOL_REQUIRED,
    ERR_TRIP_WINDOW_CONFLICT,
)
from serializers import serialize_trip
from services import (
    recompute_cold_chain, refresh_trip_loaded_cases, trip_orders,
    run_breach_cascade, generate_orders_for_trip,
)

bp = Blueprint("trips", __name__)


def get_trip_or_404(trip_id):
    t = DB.trips.get(trip_id)
    if t is None:
        raise err(ERR_TRIP_NOT_FOUND, "TruckTrip id not found")
    return t


def owner_check_trip(user_id, trip):
    route = DB.routes.get(trip["route_id"])
    if route is None or route["distributor_id"] != user_id:
        raise err(ERR_OWNERSHIP_MISMATCH, "Caller does not own the trip's route")


def driver_check_trip(user_id, trip):
    if trip["driver_id"] != user_id:
        raise err(ERR_OWNERSHIP_MISMATCH, "Caller is not the trip's driver")


@bp.post("/dairy/trips")
def create_trip():
    user_id, _role = require_role("DistributorOwner")
    body = get_json_body()
    check_unknown_fields(body, {"route_id", "driver_id", "service_date",
                                "truck_plate", "case_capacity",
                                "planned_depart_at", "planned_return_at"})
    require_fields(body, ["route_id", "driver_id", "service_date", "truck_plate",
                          "case_capacity", "planned_depart_at", "planned_return_at"])
    route = DB.routes.get(body["route_id"])
    if route is None:
        raise err(ERR_ROUTE_NOT_FOUND, "Route id not found")
    owner_check_trip_route = route["distributor_id"] != user_id
    if owner_check_trip_route:
        raise err(ERR_OWNERSHIP_MISMATCH, "Caller does not own the route")
    driver = DB.drivers.get(body["driver_id"])
    if driver is None:
        raise err(ERR_DRIVER_NOT_FOUND, "Driver id not found")
    service_date = opt_date_str(body, "service_date")
    truck_plate = body["truck_plate"]
    if not isinstance(truck_plate, str):
        raise err(ERR_INVALID_REQUEST, "truck_plate must be a string")
    case_capacity = opt_int(body, "case_capacity", gt=0)
    depart_raw = opt_iso_dt(body, "planned_depart_at")
    return_raw = opt_iso_dt(body, "planned_return_at")
    if driver["distributor_id"] != route["distributor_id"]:
        raise err(ERR_INVALID_REQUEST, "Driver must belong to the route's owning distributor")
    depart_dt = parse_iso(depart_raw)
    return_dt = parse_iso(return_raw)
    if not (return_dt > depart_dt):
        raise err(ERR_INVALID_REQUEST, "planned_return_at must be strictly later than planned_depart_at")
    # Driver double-booking: half-open [depart, return) overlap; non-CANCELLED
    # trips only; back-to-back allowed.
    for t in DB.trips.values():
        if t["driver_id"] != driver["id"] or t["status"] == "CANCELLED":
            continue
        existing_start = parse_iso(t["planned_depart_at"])
        existing_end = parse_iso(t["planned_return_at"])
        if depart_dt < existing_end and existing_start < return_dt:
            raise err(ERR_TRIP_WINDOW_CONFLICT,
                      "Driver already holds a non-CANCELLED trip overlapping this window")
    t = base_fields()
    t.update({
        "route_id": route["id"],
        "driver_id": driver["id"],
        "service_date": service_date,
        "truck_plate": truck_plate,
        "case_capacity": case_capacity,
        "planned_depart_at": format_iso_ms(depart_dt),
        "planned_return_at": format_iso_ms(return_dt),
        "status": "PLANNED",
        "excursion_minutes": 0.0,
        "cold_chain_breach": False,
        "loaded_cases": 0,
        "delivered_cases": 0,
    })
    DB.trips[t["id"]] = t
    return success_object(serialize_trip(t), status=201)


@bp.get("/dairy/trips/<tripId>")
def get_trip(tripId):
    require_any()
    return success_object(serialize_trip(get_trip_or_404(tripId)))


@bp.get("/dairy/trips")
def list_trips():
    require_any()
    items = list(DB.trips.values())
    route_id = request.args.get("route_id")
    if route_id is not None:
        items = [t for t in items if t["route_id"] == route_id]
    driver_id = request.args.get("driver_id")
    if driver_id is not None:
        items = [t for t in items if t["driver_id"] == driver_id]
    service_date = request.args.get("service_date")
    if service_date is not None:
        items = [t for t in items if t["service_date"] == service_date]
    items.sort(key=lambda t: t["_seq"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_trip(t) for t in page], limit, offset, total)


@bp.post("/dairy/trips/<tripId>/depart")
def depart_trip(tripId):
    user_id, _role = require_role("RouteDriver")
    t = get_trip_or_404(tripId)
    driver_check_trip(user_id, t)
    if t["status"] != "PLANNED":
        raise err(ERR_TRIP_NOT_PLANNED, "Trip must be PLANNED to depart")
    # Transition preconditions evaluate in narrative order (PRD §2.5):
    # pre-cool gate precedes the PLANNED-order gate.
    precool_ok = any(
        r["trip_id"] == t["id"] and r["zone"] == "BOX"
        and r["temp_tenths_f"] <= 400 and r.get("_trip_status") == "PLANNED"
        for r in DB.temperature_readings.values()
    )
    if not precool_ok:
        raise err(ERR_COLD_CHAIN_PRECOOL_REQUIRED,
                  "A BOX-zone reading at or below 40.0F recorded while PLANNED is required")
    blocking = any(
        o["fulfillment_status"] == "PLANNED" for o in trip_orders(t["id"])
    )
    if blocking:
        raise err(ERR_ORDER_NOT_CONFIRMABLE,
                  "Every order on the trip must be CONFIRMED or CANCELLED before departure")
    apply_changes(t, {"status": "DEPARTED"})
    return success_object(serialize_trip(t))


@bp.post("/dairy/trips/<tripId>/complete")
def complete_trip(tripId):
    user_id, _role = require_role("RouteDriver")
    t = get_trip_or_404(tripId)
    driver_check_trip(user_id, t)
    if t["status"] != "DEPARTED":
        raise err(ERR_TRIP_NOT_DEPARTED, "Trip must be DEPARTED to complete")
    not_delivered = any(
        o["fulfillment_status"] not in ("DELIVERED", "CANCELLED")
        for o in trip_orders(t["id"])
    )
    if not_delivered:
        raise err(ERR_ORDER_NOT_DELIVERABLE,
                  "Every order on the trip must be DELIVERED before completion")
    # Finalize: trailing above-threshold BOX reading accrues until now.
    recompute_cold_chain(t, closing_dt=now())
    t["status"] = "COMPLETED"
    touch(t)
    return success_object(serialize_trip(t))


@bp.post("/dairy/trips/<tripId>/cancel")
def cancel_trip(tripId):
    user_id, _role = require_role("DistributorOwner")
    t = get_trip_or_404(tripId)
    owner_check_trip(user_id, t)
    if t["status"] != "PLANNED":
        raise err(ERR_TRIP_NOT_PLANNED, "Trip must be PLANNED to cancel")
    has_confirmed = any(
        o["fulfillment_status"] == "CONFIRMED" for o in trip_orders(t["id"])
    )
    if has_confirmed:
        raise err(ERR_ORDER_NOT_CANCELLABLE,
                  "Trip holds a CONFIRMED order and cannot be cancelled")
    t["status"] = "CANCELLED"
    touch(t)
    for o in trip_orders(t["id"]):
        if o["fulfillment_status"] == "PLANNED":
            o["fulfillment_status"] = "CANCELLED"
            touch(o)
    refresh_trip_loaded_cases(t)
    return success_object(serialize_trip(t))


@bp.post("/dairy/trips/<tripId>/qa-review")
def qa_review_trip(tripId):
    require_role("QualityInspector")
    t = get_trip_or_404(tripId)
    if t["status"] != "COMPLETED":
        raise err(ERR_TRIP_NOT_COMPLETED, "QA review requires a COMPLETED trip")
    if not t["cold_chain_breach"]:
        raise err(ERR_TRIP_NOT_COMPLETED, "QA review requires cold_chain_breach == true")
    apply_changes(t, {"status": "QA_REVIEW"})
    return success_object(serialize_trip(t))


@bp.post("/dairy/trips/<tripId>/adjudicate")
def adjudicate_trip(tripId):
    require_role("QualityInspector")
    t = get_trip_or_404(tripId)
    body = get_json_body()
    check_unknown_fields(body, {"verdict"})
    require_fields(body, ["verdict"])
    verdict = opt_enum(body, "verdict", {"CLEAR", "CONFIRM_BREACH"})
    if t["status"] != "QA_REVIEW":
        raise err(ERR_TRIP_NOT_IN_QA_REVIEW, "Adjudication requires a trip in QA_REVIEW")
    if verdict == "CLEAR":
        t["status"] = "RECONCILED"
        t["cold_chain_breach"] = False
        touch(t)
        return success_object(serialize_trip(t))
    # CONFIRM_BREACH: five-level cascade.
    t["status"] = "BREACH_CONFIRMED"
    touch(t)
    run_breach_cascade(t)
    return success_object(serialize_trip(t))


@bp.post("/dairy/trips/<tripId>/reconcile")
def reconcile_trip(tripId):
    user_id, _role = require_role("DistributorOwner")
    t = get_trip_or_404(tripId)
    owner_check_trip(user_id, t)
    if t["status"] != "COMPLETED":
        raise err(ERR_TRIP_NOT_COMPLETED, "Reconcile requires a COMPLETED trip")
    if t["cold_chain_breach"]:
        raise err(ERR_TRIP_NOT_COMPLETED,
                  "A breached trip must pass through QA review")
    apply_changes(t, {"status": "RECONCILED"})
    return success_object(serialize_trip(t))


@bp.post("/dairy/trips/<tripId>/generate-orders")
def generate_orders(tripId):
    user_id, _role = require_role("DistributorOwner")
    t = get_trip_or_404(tripId)
    owner_check_trip(user_id, t)
    route = DB.routes.get(t["route_id"])
    if route is None or route["status"] != "ACTIVE":
        raise err(ERR_ROUTE_NOT_ACTIVE, "The trip's route must be ACTIVE")
    if t["status"] != "PLANNED":
        raise err(ERR_TRIP_NOT_PLANNED, "Order generation requires a PLANNED trip")
    created_ids, skipped_ids = generate_orders_for_trip(t)
    return success_object({
        "created_count": len(created_ids),
        "created_order_ids": created_ids,
        "skipped_store_ids": skipped_ids,
    })
