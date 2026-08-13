"""Unit, meter-reading, and fuel-event endpoints."""
from flask import Blueprint

import store
from auth import authenticate, authorize, ALL_ROLES
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_HOUR_METER_REGRESSION, ERR_FUEL_PROGRAM_MISMATCH,
)
from util import (
    body_json, req_str, req_int, req_number, opt_number, opt_str,
    new_record, new_child_record, bump, success_object, list_response, get_or_404,
)
import services

bp = Blueprint("units", __name__)


@bp.post("/fleet/units")
def create_unit():
    _, role = authenticate()
    authorize(role, ["FleetManager"])
    body = body_json()
    serial = req_str(body, "serial_number")
    model = req_str(body, "model")
    power_type = req_str(body, "power_type")
    if power_type not in ("BATTERY", "LP"):
        raise_err(ERR_INVALID_REQUEST, "power_type must be BATTERY or LP")
    disposition = req_str(body, "disposition")
    if disposition not in ("NEW_SALE", "RENTAL_FLEET", "USED_SALE"):
        raise_err(ERR_INVALID_REQUEST, "disposition must be NEW_SALE, RENTAL_FLEET, or USED_SALE")
    daily = req_int(body, "daily_rate_cents")
    weekly = req_int(body, "weekly_rate_cents")
    monthly = req_int(body, "monthly_rate_cents")
    pm_interval = req_int(body, "pm_interval_hours")
    if daily < 1 or weekly < 1 or monthly < 1:
        raise_err(ERR_INVALID_REQUEST, "rates must be >= 1")
    if pm_interval < 1:
        raise_err(ERR_INVALID_REQUEST, "pm_interval_hours must be >= 1")
    rec = new_record()
    rec.update({
        "serial_number": serial,
        "model": model,
        "power_type": power_type,
        "fuel_program": power_type,  # mirrors
        "disposition": disposition,
        "daily_rate_cents": daily,
        "weekly_rate_cents": weekly,
        "monthly_rate_cents": monthly,
        "pm_interval_hours": pm_interval,
        "hour_meter": 0,
        "last_pm_hours": 0,
        "next_pm_due_hours": pm_interval,
        "maintenance_posture": "PM_OK",
        "availability_status": "AVAILABLE",
        "resale_price_cents": None,
        "utilization_pct_90d": 0.0,
        "_last_pm_trigger_customer_id": None,
    })
    store.units[rec["id"]] = rec
    return success_object(services.serialize_unit(rec), 201)


@bp.get("/fleet/units/<uid>")
def get_unit(uid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    u = get_or_404(store.units, uid, "Unit")
    return success_object(services.serialize_unit(u), 200)


@bp.post("/fleet/units/<uid>/meter-readings")
def create_meter_reading(uid):
    _, role = authenticate()
    authorize(role, ["FleetManager"])
    body = body_json()
    reading_hours = req_number(body, "reading_hours")
    note = opt_str(body, "note")
    u = get_or_404(store.units, uid, "Unit")
    if u["availability_status"] == "SOLD":
        raise_err(ERR_INVALID_STATE, "Cannot record meter readings on a SOLD unit")
    if reading_hours <= u["hour_meter"]:
        raise_err(ERR_HOUR_METER_REGRESSION, "reading_hours must be strictly greater than current hour_meter")
    rec = new_child_record()
    rec.update({
        "unit_id": u["id"],
        "reading_hours": reading_hours,
        "note": note,
    })
    store.meter_readings[rec["id"]] = rec
    u["hour_meter"] = reading_hours
    services.recompute_posture(u)
    bump(u)
    return success_object(services.serialize_meter_reading(rec), 201)


@bp.get("/fleet/units/<uid>/meter-readings")
def list_meter_readings(uid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    u = get_or_404(store.units, uid, "Unit")
    readings = [r for r in store.meter_readings.values() if r["unit_id"] == u["id"]]
    return list_response(readings, services.serialize_meter_reading)


@bp.post("/fleet/units/<uid>/fuel-events")
def create_fuel_event(uid):
    _, role = authenticate()
    authorize(role, ["FleetManager", "Technician"])
    body = body_json()
    event_type = req_str(body, "event_type")
    if event_type not in ("CHARGE", "SWAP", "LP_REFILL"):
        raise_err(ERR_INVALID_REQUEST, "event_type must be CHARGE, SWAP, or LP_REFILL")
    kwh = opt_number(body, "kwh", 0)
    cylinders = opt_number(body, "cylinders", 0)
    if cylinders is None:
        cylinders = 0
    if not isinstance(cylinders, int) or cylinders < 0:
        raise_err(ERR_INVALID_REQUEST, "cylinders must be an integer >= 0")
    if kwh < 0:
        raise_err(ERR_INVALID_REQUEST, "kwh must be >= 0")
    u = get_or_404(store.units, uid, "Unit")
    if u["availability_status"] == "SOLD":
        raise_err(ERR_INVALID_STATE, "Cannot record fuel events on a SOLD unit")
    if u["fuel_program"] == "BATTERY" and event_type not in ("CHARGE", "SWAP"):
        raise_err(ERR_FUEL_PROGRAM_MISMATCH, "BATTERY units accept only CHARGE or SWAP")
    if u["fuel_program"] == "LP" and event_type != "LP_REFILL":
        raise_err(ERR_FUEL_PROGRAM_MISMATCH, "LP units accept only LP_REFILL")
    cost = services.fuel_event_cost(u, event_type, kwh, cylinders)
    rec = new_child_record()
    rec.update({
        "unit_id": u["id"],
        "event_type": event_type,
        "kwh": kwh,
        "cylinders": cylinders,
        "cost_cents": cost,
    })
    store.fuel_events[rec["id"]] = rec
    return success_object(services.serialize_fuel_event(rec), 201)


@bp.get("/fleet/units/<uid>/fuel-events")
def list_fuel_events(uid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    u = get_or_404(store.units, uid, "Unit")
    events = [f for f in store.fuel_events.values() if f["unit_id"] == u["id"]]
    return list_response(events, services.serialize_fuel_event)
