"""Clock, Driver, DutyEvent, SafetyEvent, Tractor, CustomerAccount, Lane,
StateFuelRate endpoints."""
from flask import Blueprint, request

from common import (ApiError, require_role, get_body, ok, ok_list, pagination,
                    created_order, paged, req_str, opt_str, req_int, opt_int,
                    req_enum, req_dt, opt_dt, opt_bool, ERR_INVALID,
                    ERR_DRIVER_MISMATCH, ERR_STALE)
from store import store, now, init_common, init_telemetry, touch
import services as svc

bp = Blueprint("fleet", __name__)

ALL = ["FleetAdmin", "LoadPlanner", "Dispatcher", "SafetyOfficer",
       "PayrollClerk", "Driver"]

PAY_MODELS = ("MILEAGE", "PERCENTAGE")
EVENT_TYPES = ("OFF_DUTY", "SLEEPER", "DRIVING", "ON_DUTY")
MANUAL_SAFETY_KINDS = ("INSPECTION_VIOLATION", "CRASH_AT_FAULT")


def get_driver_or_404(driver_id):
    d = store.drivers.get(driver_id)
    if d is None:
        raise ApiError("ERR_DRIVER_NOT_FOUND", 404, "Driver id does not exist")
    return d


def get_tractor_or_404(tractor_id):
    t = store.tractors.get(tractor_id)
    if t is None:
        raise ApiError("ERR_TRACTOR_NOT_FOUND", 404, "Tractor id does not exist")
    return t


def get_customer_or_404(customer_id):
    c = store.customers.get(customer_id)
    if c is None:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND", 404, "CustomerAccount id does not exist")
    return c


def get_lane_or_404(lane_id):
    ln = store.lanes.get(lane_id)
    if ln is None:
        raise ApiError("ERR_LANE_NOT_FOUND", 404, "Lane id does not exist")
    return ln


def get_fuel_rate_or_404(rate_id):
    r = store.fuel_rates.get(rate_id)
    if r is None:
        raise ApiError("ERR_FUEL_RATE_NOT_FOUND", 404, "StateFuelRate id does not exist")
    return r


def get_safety_event_or_404(ev_id):
    ev = store.safety_events.get(ev_id)
    if ev is None:
        raise ApiError("ERR_SAFETY_EVENT_NOT_FOUND", 404, "SafetyEvent id does not exist")
    return ev


# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.4)
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_role(["FleetAdmin"])
    b = get_body()
    to = req_dt(b, "to_iso8601")
    store.clock = to
    return ok({"current_utc": to})


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------

@bp.post("/drivers")
def create_driver():
    require_role(["FleetAdmin"])
    b = get_body()
    cdl = req_str(b, "cdl_number")
    full_name = req_str(b, "full_name")
    home_terminal = req_str(b, "home_terminal")
    pay_model = req_enum(b, "pay_model", PAY_MODELS)
    rate = opt_int(b, "pay_rate_cents_per_mile", min_v=1)
    bpct = opt_int(b, "pay_percentage_bp", min_v=1, max_v=10000)
    hired_at = req_dt(b, "hired_at")
    last_home_at = req_dt(b, "last_home_at")
    for d in store.drivers.values():
        if d["cdl_number"] == cdl:
            raise ApiError(ERR_INVALID, 400, "cdl_number must be unique across drivers")
    if pay_model == "MILEAGE" and rate is None:
        raise ApiError("ERR_PAY_CONFIG_INCOMPLETE", 422,
                       "MILEAGE pay model requires pay_rate_cents_per_mile")
    if pay_model == "PERCENTAGE" and bpct is None:
        raise ApiError("ERR_PAY_CONFIG_INCOMPLETE", 422,
                       "PERCENTAGE pay model requires pay_percentage_bp")
    d = init_common({
        "cdl_number": cdl,
        "full_name": full_name,
        "home_terminal": home_terminal,
        "pay_model": pay_model,
        "pay_rate_cents_per_mile": rate,
        "pay_percentage_bp": bpct,
        "hired_at": hired_at,
        "last_home_at": last_home_at,
        "employment_status": "ACTIVE",
        "duty_status": "OFF_DUTY",
        "safety_score": 100,
    })
    store.drivers[d["id"]] = d
    return ok(d, 201)


@bp.get("/drivers")
def list_drivers():
    require_role(ALL)
    limit, offset = pagination()
    status = request.args.get("status")
    items = list(store.drivers.values())
    if status is not None:
        items = [d for d in items if d["employment_status"] == status]
    items = created_order(items)
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/drivers/<driver_id>")
def get_driver(driver_id):
    require_role(ALL)
    return ok(get_driver_or_404(driver_id))


@bp.patch("/drivers/<driver_id>")
def patch_driver(driver_id):
    require_role(["FleetAdmin"])
    d = get_driver_or_404(driver_id)
    b = get_body()
    expected = req_int(b, "expected_driver_version")
    pay_model = b.get("pay_model")
    if pay_model is not None and pay_model not in PAY_MODELS:
        raise ApiError(ERR_INVALID, 400, "Field 'pay_model' must be MILEAGE or PERCENTAGE")
    rate = opt_int(b, "pay_rate_cents_per_mile", min_v=1)
    bpct = opt_int(b, "pay_percentage_bp", min_v=1, max_v=10000)
    home_terminal = opt_str(b, "home_terminal")
    if expected != d["version"]:
        raise ApiError(ERR_STALE, 412,
                       "expected_driver_version does not match the current Driver version")
    new_model = pay_model if pay_model is not None else d["pay_model"]
    new_rate = rate if rate is not None else d["pay_rate_cents_per_mile"]
    new_bpct = bpct if bpct is not None else d["pay_percentage_bp"]
    if new_model == "MILEAGE" and new_rate is None:
        raise ApiError("ERR_PAY_CONFIG_INCOMPLETE", 422,
                       "MILEAGE pay model requires pay_rate_cents_per_mile")
    if new_model == "PERCENTAGE" and new_bpct is None:
        raise ApiError("ERR_PAY_CONFIG_INCOMPLETE", 422,
                       "PERCENTAGE pay model requires pay_percentage_bp")
    d["pay_model"] = new_model
    d["pay_rate_cents_per_mile"] = new_rate
    d["pay_percentage_bp"] = new_bpct
    if home_terminal is not None:
        d["home_terminal"] = home_terminal
    touch(d)
    return ok(d)


@bp.post("/drivers/<driver_id>/suspend")
def suspend_driver(driver_id):
    require_role(["SafetyOfficer"])
    d = get_driver_or_404(driver_id)
    if d["employment_status"] != "ACTIVE":
        raise ApiError("ERR_DRIVER_NOT_ACTIVE", 409,
                       "Suspend requires employment_status ACTIVE")
    d["employment_status"] = "SUSPENDED"
    touch(d)
    svc.driver_employment_cascade(d)
    return ok(d)


@bp.post("/drivers/<driver_id>/reinstate")
def reinstate_driver(driver_id):
    require_role(["SafetyOfficer"])
    d = get_driver_or_404(driver_id)
    if d["employment_status"] != "SUSPENDED":
        raise ApiError("ERR_DRIVER_NOT_SUSPENDED", 409,
                       "Reinstate requires employment_status SUSPENDED")
    d["employment_status"] = "ACTIVE"
    touch(d)
    return ok(d)


@bp.post("/drivers/<driver_id>/terminate")
def terminate_driver(driver_id):
    require_role(["FleetAdmin"])
    d = get_driver_or_404(driver_id)
    if d["employment_status"] == "TERMINATED":
        raise ApiError("ERR_DRIVER_ALREADY_TERMINATED", 409,
                       "Driver is already TERMINATED")
    d["employment_status"] = "TERMINATED"
    touch(d)
    svc.driver_employment_cascade(d)
    return ok(d)


@bp.get("/drivers/<driver_id>/hos-status")
def hos_status(driver_id):
    require_role(ALL)
    d = get_driver_or_404(driver_id)
    drive, window, cycle, break_blocked = svc.hos_projection(driver_id)
    return ok({
        "drive_11h_remaining_minutes": svc.as_int(drive),
        "window_14h_remaining_minutes": svc.as_int(window),
        "cycle_70h_remaining_minutes": svc.as_int(cycle),
        "break_blocked": break_blocked,
        "duty_status": d["duty_status"],
    })


@bp.get("/drivers/<driver_id>/duty-events")
def list_duty_events(driver_id):
    require_role(ALL)
    get_driver_or_404(driver_id)
    limit, offset = pagination()
    items = svc.driver_duty_events(driver_id)  # occurred_at ASC ordering
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/drivers/<driver_id>/duty-events")
def create_duty_event(driver_id):
    uid, role = require_role(["Driver", "Dispatcher"])
    d = get_driver_or_404(driver_id)
    b = get_body()
    event_type = req_enum(b, "event_type", EVENT_TYPES)
    occurred_at = req_dt(b, "occurred_at")
    if occurred_at > now():
        raise ApiError(ERR_INVALID, 400,
                       "occurred_at must not be after the logical now")
    at_home = opt_bool(b, "at_home", False)
    trip_id = opt_str(b, "trip_id")
    if trip_id is not None and trip_id not in store.trips:
        raise ApiError("ERR_TRIP_NOT_FOUND", 404, "Trip id does not exist")
    if role == "Driver" and uid != driver_id:
        raise ApiError(ERR_DRIVER_MISMATCH, 403,
                       "A Driver may append duty events only to their own record")
    if d["employment_status"] != "ACTIVE":
        raise ApiError("ERR_DRIVER_NOT_ACTIVE", 409,
                       "Duty events require employment_status ACTIVE")
    prev = svc.driver_duty_events(driver_id)
    if prev and occurred_at <= prev[-1]["occurred_at"]:
        raise ApiError("ERR_DUTY_EVENT_OUT_OF_ORDER", 422,
                       "occurred_at must be strictly greater than the previous duty event")
    # Illegal-driving screen evaluated on the stream before this event.
    creates_violation = False
    if event_type == "DRIVING":
        drive, window, cycle, break_blocked = svc.hos_projection(driver_id)
        if break_blocked or drive <= 0 or window <= 0 or cycle <= 0:
            creates_violation = True
    ev = init_telemetry({
        "driver_id": driver_id,
        "trip_id": trip_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "at_home": at_home,
    })
    store.duty_events[ev["id"]] = ev
    d["duty_status"] = event_type
    if event_type == "OFF_DUTY" and at_home:
        d["last_home_at"] = occurred_at
    touch(d)
    if creates_violation:
        sev = init_common({
            "driver_id": driver_id,
            "kind": "HOS_VIOLATION",
            "severity_points": 5,
            "occurred_at": occurred_at,
            "source": "AUTO_HOS",
            "voided": False,
        })
        store.safety_events[sev["id"]] = sev
        svc.recompute_driver_score(d)
    return ok(ev, 201)


@bp.get("/drivers/<driver_id>/safety-events")
def list_safety_events(driver_id):
    require_role(ALL)
    get_driver_or_404(driver_id)
    limit, offset = pagination()
    items = created_order([e for e in store.safety_events.values()
                           if e["driver_id"] == driver_id])
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/drivers/<driver_id>/safety-events")
def create_safety_event(driver_id):
    require_role(["SafetyOfficer"])
    d = get_driver_or_404(driver_id)
    b = get_body()
    kind = b.get("kind")
    if kind == "HOS_VIOLATION":
        raise ApiError(ERR_INVALID, 400,
                       "HOS_VIOLATION safety events are system-created only")
    if kind not in MANUAL_SAFETY_KINDS:
        raise ApiError(ERR_INVALID, 400,
                       "Field 'kind' must be INSPECTION_VIOLATION or CRASH_AT_FAULT")
    occurred_at = req_dt(b, "occurred_at")
    if occurred_at > now():
        raise ApiError(ERR_INVALID, 400,
                       "occurred_at must not be after the logical now")
    severity = opt_int(b, "severity_points", min_v=1, max_v=100)
    if severity is None:
        severity = 1
    ev = init_common({
        "driver_id": driver_id,
        "kind": kind,
        "severity_points": severity,
        "occurred_at": occurred_at,
        "source": "MANUAL",
        "voided": False,
    })
    store.safety_events[ev["id"]] = ev
    svc.recompute_driver_score(d)
    return ok(ev, 201)


@bp.get("/safety-events/<ev_id>")
def get_safety_event(ev_id):
    require_role(ALL)
    return ok(get_safety_event_or_404(ev_id))


@bp.post("/safety-events/<ev_id>/void")
def void_safety_event(ev_id):
    require_role(["SafetyOfficer"])
    ev = get_safety_event_or_404(ev_id)
    if ev["voided"]:
        raise ApiError("ERR_SAFETY_EVENT_NOT_VOIDABLE", 409,
                       "Safety event is already voided")
    ev["voided"] = True
    touch(ev)
    svc.recompute_driver_score(store.drivers[ev["driver_id"]])
    return ok(ev)


@bp.get("/drivers/<driver_id>/fuel-purchases")
def list_driver_fuel_purchases(driver_id):
    require_role(ALL)
    get_driver_or_404(driver_id)
    limit, offset = pagination()
    items = created_order([p for p in store.fuel_purchases.values()
                           if p["driver_id"] == driver_id])
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/drivers/<driver_id>/settlements")
def list_driver_settlements(driver_id):
    require_role(ALL)
    get_driver_or_404(driver_id)
    limit, offset = pagination()
    items = created_order([s for s in store.settlements.values()
                           if s["driver_id"] == driver_id])
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Tractors
# ---------------------------------------------------------------------------

@bp.post("/tractors")
def create_tractor():
    require_role(["FleetAdmin"])
    b = get_body()
    unit_number = req_str(b, "unit_number")
    home_terminal = req_str(b, "home_terminal")
    odometer = req_int(b, "odometer_miles", min_v=0)
    state_code = req_str(b, "current_state_code")
    capacity = req_int(b, "tank_capacity_gallons", min_v=1)
    fuel = req_int(b, "current_fuel_gallons", min_v=0)
    if fuel > capacity:
        raise ApiError(ERR_INVALID, 400,
                       "current_fuel_gallons must not exceed tank_capacity_gallons")
    for t in store.tractors.values():
        if t["unit_number"] == unit_number:
            raise ApiError(ERR_INVALID, 400, "unit_number must be unique across tractors")
    t = init_common({
        "unit_number": unit_number,
        "home_terminal": home_terminal,
        "status": "AVAILABLE",
        "odometer_miles": odometer,
        "current_state_code": state_code,
        "tank_capacity_gallons": capacity,
        "current_fuel_gallons": fuel,
    })
    store.tractors[t["id"]] = t
    return ok(t, 201)


@bp.get("/tractors")
def list_tractors():
    require_role(ALL)
    limit, offset = pagination()
    status = request.args.get("status")
    items = list(store.tractors.values())
    if status:
        items = [t for t in items if t["status"] == status]
    items = created_order(items)
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/tractors/<tractor_id>")
def get_tractor(tractor_id):
    require_role(ALL)
    return ok(get_tractor_or_404(tractor_id))


@bp.post("/tractors/<tractor_id>/out-of-service")
def tractor_out_of_service(tractor_id):
    require_role(["FleetAdmin"])
    t = get_tractor_or_404(tractor_id)
    if t["status"] != "AVAILABLE":
        raise ApiError("ERR_TRACTOR_NOT_AVAILABLE", 409,
                       "Out-of-service requires status AVAILABLE")
    t["status"] = "OUT_OF_SERVICE"
    touch(t)
    return ok(t)


@bp.post("/tractors/<tractor_id>/return-to-service")
def tractor_return_to_service(tractor_id):
    require_role(["FleetAdmin"])
    t = get_tractor_or_404(tractor_id)
    if t["status"] != "OUT_OF_SERVICE":
        raise ApiError("ERR_TRACTOR_NOT_OUT_OF_SERVICE", 409,
                       "Return-to-service requires status OUT_OF_SERVICE")
    t["status"] = "AVAILABLE"
    touch(t)
    return ok(t)


@bp.get("/tractors/<tractor_id>/trips")
def list_tractor_trips(tractor_id):
    require_role(ALL)
    get_tractor_or_404(tractor_id)
    limit, offset = pagination()
    items = created_order([t for t in store.trips.values()
                           if t["tractor_id"] == tractor_id])
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Customer accounts
# ---------------------------------------------------------------------------

@bp.post("/customers")
def create_customer():
    require_role(["FleetAdmin"])
    b = get_body()
    name = req_str(b, "name")
    c = init_common({"name": name, "status": "ACTIVE"})
    store.customers[c["id"]] = c
    return ok(c, 201)


@bp.get("/customers")
def list_customers():
    require_role(ALL)
    limit, offset = pagination()
    items = created_order(list(store.customers.values()))
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/customers/<customer_id>")
def get_customer(customer_id):
    require_role(ALL)
    return ok(get_customer_or_404(customer_id))


@bp.post("/customers/<customer_id>/credit-hold")
def credit_hold(customer_id):
    require_role(["LoadPlanner"])
    c = get_customer_or_404(customer_id)
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_INVALID_STATE", 409,
                       "Credit hold requires status ACTIVE")
    c["status"] = "CREDIT_HOLD"
    touch(c)
    return ok(c)


@bp.post("/customers/<customer_id>/release-credit-hold")
def release_credit_hold(customer_id):
    require_role(["LoadPlanner"])
    c = get_customer_or_404(customer_id)
    if c["status"] != "CREDIT_HOLD":
        raise ApiError("ERR_CUSTOMER_INVALID_STATE", 409,
                       "Release requires status CREDIT_HOLD")
    c["status"] = "ACTIVE"
    touch(c)
    return ok(c)


@bp.get("/customers/<customer_id>/loads")
def list_customer_loads(customer_id):
    require_role(ALL)
    get_customer_or_404(customer_id)
    limit, offset = pagination()
    items = created_order([l for l in store.loads.values()
                           if l["customer_id"] == customer_id])
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Lanes
# ---------------------------------------------------------------------------

@bp.post("/lanes")
def create_lane():
    require_role(["LoadPlanner"])
    b = get_body()
    origin = req_str(b, "origin_state")
    destination = req_str(b, "destination_state")
    loaded_miles = req_int(b, "loaded_miles", min_v=1)
    rpm_floor = req_int(b, "rpm_floor_cents", min_v=0)
    ln = init_common({
        "origin_state": origin,
        "destination_state": destination,
        "loaded_miles": loaded_miles,
        "rpm_floor_cents": rpm_floor,
    })
    store.lanes[ln["id"]] = ln
    return ok(ln, 201)


@bp.get("/lanes")
def list_lanes():
    require_role(ALL)
    limit, offset = pagination()
    items = created_order(list(store.lanes.values()))
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/lanes/<lane_id>")
def get_lane(lane_id):
    require_role(ALL)
    return ok(get_lane_or_404(lane_id))


# ---------------------------------------------------------------------------
# State fuel rates
# ---------------------------------------------------------------------------

@bp.post("/state-fuel-rates")
def create_fuel_rate():
    require_role(["FleetAdmin"])
    b = get_body()
    state_code = req_str(b, "state_code")
    tax = req_int(b, "tax_cents_per_gallon", min_v=0)
    pump = req_int(b, "avg_pump_price_cents", min_v=1)
    eff_from = req_dt(b, "effective_from")
    eff_to = opt_dt(b, "effective_to")
    if eff_to is not None and eff_to < eff_from:
        raise ApiError(ERR_INVALID, 400,
                       "effective_to must not be before effective_from")
    for r in store.fuel_rates.values():
        if r["state_code"] != state_code:
            continue
        # Closed intervals: touching endpoints conflict.
        left = (r["effective_to"] is None) or (eff_from <= r["effective_to"])
        right = (eff_to is None) or (eff_to >= r["effective_from"])
        if left and right:
            raise ApiError("ERR_FUEL_RATE_WINDOW_OVERLAP", 422,
                           "Effective window overlaps an existing window for this state_code")
    r = init_common({
        "state_code": state_code,
        "tax_cents_per_gallon": tax,
        "avg_pump_price_cents": pump,
        "effective_from": eff_from,
        "effective_to": eff_to,
    })
    store.fuel_rates[r["id"]] = r
    return ok(r, 201)


@bp.get("/state-fuel-rates")
def list_fuel_rates():
    require_role(ALL)
    limit, offset = pagination()
    state_code = request.args.get("state_code")
    items = list(store.fuel_rates.values())
    if state_code:
        items = [r for r in items if r["state_code"] == state_code]
    items = created_order(items)
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/state-fuel-rates/<rate_id>")
def get_fuel_rate(rate_id):
    require_role(ALL)
    return ok(get_fuel_rate_or_404(rate_id))
