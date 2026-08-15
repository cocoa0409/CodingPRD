"""Bus routes: register, get, list, pm-status, retire, nested lists."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from errors import err
from httpkit import (require_roles, body, req_str, req_int, opt_int, opt_str,
                     req_date, paginate, sort_default, success)
from store import db, init_common, mark_dirty, fmt_date, clock_date
from services import domain as dom
from services import cascades
from services import serializers as ser

bp = Blueprint("buses", __name__)

ALL = ("FleetManager", "MaintenanceSupervisor", "Mechanic", "Operator",
       "PartsClerk", "WarrantyClerk")


def get_bus_or_404(bus_id):
    bus = db["buses"].get(bus_id)
    if bus is None:
        raise err("ERR_NOT_FOUND", f"Bus {bus_id} not found")
    return bus


@bp.post("/fleet/buses")
def create_bus():
    require_roles("FleetManager")
    data = body()
    fleet_number = req_str(data, "fleet_number")
    vin = req_str(data, "vin")
    model_year = req_int(data, "model_year")
    in_service_date = req_date(data, "in_service_date")
    initial_odometer = req_int(data, "initial_odometer_miles")
    replacement_cost = req_int(data, "replacement_cost_cents")
    base_miles = req_int(data, "base_warranty_expiry_miles")
    base_date = req_date(data, "base_warranty_expiry_date")
    overhaul_interval = req_int(data, "overhaul_interval_miles")
    ext_miles = opt_int(data, "extended_warranty_limit_miles")
    ext_months = opt_int(data, "extended_warranty_limit_months")
    retirement_reason = opt_str(data, "retirement_reason")
    if initial_odometer < 0:
        raise err("ERR_VALIDATION", "initial_odometer_miles must be >= 0")

    bus = init_common({
        "fleet_number": fleet_number,
        "vin": vin,
        "model_year": model_year,
        "in_service_date": fmt_date(in_service_date),
        "initial_odometer_miles": initial_odometer,
        "odometer_miles": initial_odometer,
        "replacement_cost_cents": replacement_cost,
        "base_warranty_expiry_miles": base_miles,
        "base_warranty_expiry_date": fmt_date(base_date),
        "extended_warranty_limit_miles": ext_miles,
        "extended_warranty_limit_months": ext_months,
        "overhaul_interval_miles": overhaul_interval,
        "last_overhaul_miles": 0,
        "service_status": "ACTIVE",
        "availability_status": "AVAILABLE",
        "hold_reasons": [],
        "emissions_hold": False,
        "emissions_cert_expiry_date": None,
        "last_pm_a_miles": 0,
        "last_pm_a_date": fmt_date(in_service_date),
        "last_pm_b_miles": 0,
        "last_pm_b_date": fmt_date(in_service_date),
        "last_pm_c_miles": 0,
        "last_pm_c_date": fmt_date(in_service_date),
        "pm_due_status": "CURRENT",
        "_next_pm_level": "A",
        "total_maintenance_cost_cents": 0,
        "retirement_reason": retirement_reason,
    })
    # compute initial PM status without marking the new entity dirty
    _st, _lv = dom.compute_pm_due(bus)
    bus["pm_due_status"] = _st
    bus["_next_pm_level"] = _lv
    db["buses"][bus["id"]] = bus
    dom.recompute_posture()
    return success(ser.bus(bus), code=201)


@bp.get("/fleet/buses/<bus_id>")
def get_bus(bus_id):
    require_roles(*ALL)
    bus = get_bus_or_404(bus_id)
    return success(ser.bus(bus))


@bp.get("/fleet/buses")
def list_buses():
    require_roles(*ALL)
    items = list(db["buses"].values())
    ss = None
    from flask import request
    ss = request.args.get("service_status")
    av = request.args.get("availability_status")
    if ss is not None:
        items = [b for b in items if b["service_status"] == ss]
    if av is not None:
        items = [b for b in items if b["availability_status"] == av]
    items = sort_default(items)
    page, meta_p = paginate(items)
    return success([ser.bus(b) for b in page], response_type="array",
                   pagination=meta_p)


@bp.get("/fleet/buses/<bus_id>/pm-status")
def bus_pm_status(bus_id):
    require_roles(*ALL)
    bus = get_bus_or_404(bus_id)
    from flask import request
    variant = request.args.get("variant", "MILEAGE_RATE")
    if variant not in ("MILEAGE_RATE", "CALENDAR"):
        raise err("ERR_VALIDATION", "variant must be MILEAGE_RATE or CALENDAR")
    policy = dom.active_policy()
    miles_since_a = bus["odometer_miles"] - bus["last_pm_a_miles"]
    miles_since_b = bus["odometer_miles"] - bus["last_pm_b_miles"]
    miles_since_c = bus["odometer_miles"] - bus["last_pm_c_miles"]
    avg_daily = dom.avg_daily_miles_for_bus(bus["id"])
    if policy is None:
        miles_remaining_a = None
        projected = None
    else:
        miles_remaining_a = policy["level_a_interval_miles"] - miles_since_a
        if variant == "MILEAGE_RATE":
            days_to_due = max(
                0, -(-miles_remaining_a // avg_daily)
                if miles_remaining_a >= 0 else 0)
            # ceiling division that also covers negatives -> clamped by max(0,..)
            if miles_remaining_a > 0:
                days_to_due = -(-miles_remaining_a // avg_daily)
            else:
                days_to_due = 0
            projected = fmt_date(clock_date() + timedelta(days=days_to_due))
        else:
            from datetime import datetime as _dt
            last_a = _dt.strptime(bus["last_pm_a_date"], "%Y-%m-%d").date()
            projected = fmt_date(last_a + timedelta(
                days=policy["calendar_interval_days"]))
    data = {
        "pm_due_status": bus.get("pm_due_status", "CURRENT"),
        "next_pm_level": bus.get("_next_pm_level", "A"),
        "miles_since_pm_a": miles_since_a,
        "miles_since_pm_b": miles_since_b,
        "miles_since_pm_c": miles_since_c,
        "miles_remaining_a": miles_remaining_a,
        "avg_daily_miles": avg_daily,
        "projected_due_date": projected,
        "projection_variant": variant,
    }
    return success(data)


@bp.post("/fleet/buses/<bus_id>/retire")
def retire_bus_route(bus_id):
    require_roles("FleetManager")
    bus = get_bus_or_404(bus_id)
    data = body()
    reason = opt_str(data, "retirement_reason")
    if bus["service_status"] == "RETIRED":
        raise err("ERR_ALREADY_TERMINAL", "Bus is already RETIRED")
    cascades.retire_bus(bus, reason)
    return success(ser.bus(bus))


def _nested_list(parent, coll, match, serializer):
    items = [e for e in db[coll].values() if match(e)]
    items = sort_default(items)
    page, meta_p = paginate(items)
    return success([serializer(e) for e in page], response_type="array",
                   pagination=meta_p)


@bp.get("/fleet/buses/<bus_id>/work-orders")
def bus_work_orders(bus_id):
    require_roles(*ALL)
    get_bus_or_404(bus_id)
    return _nested_list(bus_id, "work_orders",
                        lambda w: w["bus_id"] == bus_id, ser.work_order)


@bp.get("/fleet/buses/<bus_id>/warranty-claims")
def bus_claims(bus_id):
    require_roles(*ALL)
    get_bus_or_404(bus_id)
    return _nested_list(bus_id, "claims",
                        lambda c: c["bus_id"] == bus_id, ser.claim)


@bp.get("/fleet/buses/<bus_id>/defect-reports")
def bus_defects(bus_id):
    require_roles(*ALL)
    get_bus_or_404(bus_id)
    return _nested_list(bus_id, "defects",
                        lambda d: d["bus_id"] == bus_id, ser.defect)


@bp.get("/fleet/buses/<bus_id>/mileage-fuel-logs")
def bus_logs(bus_id):
    require_roles(*ALL)
    get_bus_or_404(bus_id)
    return _nested_list(bus_id, "logs",
                        lambda l: l["bus_id"] == bus_id, ser.mileage_log)


@bp.get("/fleet/buses/<bus_id>/emissions-inspections")
def bus_inspections(bus_id):
    require_roles(*ALL)
    get_bus_or_404(bus_id)
    return _nested_list(bus_id, "inspections",
                        lambda i: i["bus_id"] == bus_id, ser.inspection)
