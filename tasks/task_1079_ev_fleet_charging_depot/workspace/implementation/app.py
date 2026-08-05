"""EV-Fleet & Charging-Depot Management API — Flask application."""
import os
from flask import Flask, request

import db
import calc
from util import (
    ApiError, ok, error_response, authenticate, require_roles, get_body,
    require_fields, as_number, check_soc, paginate, sorted_by_created, D,
    round_half_up_cents, rate_at, CONNECTORS, SEVERITIES,
)

app = Flask(__name__)

ALL_ROLES = ["FleetManager", "DepotOperator", "MaintenanceTech", "Driver", "FinanceManager"]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(_e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found."))


@app.errorhandler(405)
def _handle_405(_e):
    return error_response(ApiError("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed."))


@app.errorhandler(Exception)
def _handle_generic(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INTERNAL", 500, str(err)))


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def make_entity(fields, common=True):
    ent = dict(fields)
    ent["id"] = db.new_id()
    ent["_seq"] = db.next_seq()
    ent["created_at"] = db.now()
    if common:
        ent["updated_at"] = db.now()
        ent["version"] = 1
    return ent


def touch(entity):
    entity["updated_at"] = db.now()
    entity["version"] = entity.get("version", 1) + 1


def get_or_404(collection, id_, err_id):
    ent = collection.get(id_)
    if ent is None:
        raise ApiError(err_id, 404, f"{err_id}")
    return ent


def out(entity):
    return db.serialize(entity)


def list_response(collection, filters=None):
    items = list(collection.values())
    if filters:
        for key, val in filters.items():
            if val is not None:
                items = [e for e in items if str(e.get(key)) == str(val)]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok([out(e) for e in page], 200, is_list=True, pagination=meta)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = authenticate()
    require_roles(role, ["FleetManager"])
    body = get_body()
    require_fields(body, ["to_iso8601"])
    try:
        dt = db.parse_dt(body["to_iso8601"])
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "Invalid to_iso8601 value.")
    db.set_clock(dt)
    return ok({}, 200)


# ---------------------------------------------------------------------------
# Depot
# ---------------------------------------------------------------------------
def _validate_tariff_windows(tw):
    if not isinstance(tw, list) or len(tw) == 0:
        raise ApiError("ERR_VALIDATION", 422, "tariff_windows must be a non-empty array.")
    for w in tw:
        if not isinstance(w, dict):
            raise ApiError("ERR_VALIDATION", 422, "tariff_windows entries must be objects.")
        for f in ("period", "start_hour_utc", "end_hour_utc", "rate_cents_per_kwh"):
            if w.get(f) is None:
                raise ApiError("ERR_VALIDATION", 422, f"tariff window missing {f}.")


@app.route("/fleet/depots", methods=["POST"])
def create_depot():
    _uid, role = authenticate()
    require_roles(role, ["FleetManager"])
    body = get_body()
    require_fields(body, ["name", "max_load_kw", "contracted_capacity_kw",
                          "demand_rate_cents_per_kw", "overage_rate_cents_per_kw",
                          "reimbursement_budget_cents", "tariff_windows"])
    max_load = as_number(body["max_load_kw"], "max_load_kw")
    contracted = as_number(body["contracted_capacity_kw"], "contracted_capacity_kw")
    if max_load <= 0:
        raise ApiError("ERR_VALIDATION", 422, "max_load_kw must be > 0.")
    if contracted <= 0:
        raise ApiError("ERR_VALIDATION", 422, "contracted_capacity_kw must be > 0.")
    demand_rate = as_number(body["demand_rate_cents_per_kw"], "demand_rate_cents_per_kw")
    overage_rate = as_number(body["overage_rate_cents_per_kw"], "overage_rate_cents_per_kw")
    budget = as_number(body["reimbursement_budget_cents"], "reimbursement_budget_cents")
    if demand_rate < 0 or overage_rate < 0 or budget < 0:
        raise ApiError("ERR_VALIDATION", 422, "rates and budget must be >= 0.")
    _validate_tariff_windows(body["tariff_windows"])

    depot = make_entity({
        "name": body["name"],
        "max_load_kw": max_load,
        "contracted_capacity_kw": contracted,
        "demand_rate_cents_per_kw": demand_rate,
        "overage_rate_cents_per_kw": overage_rate,
        "reimbursement_budget_cents": budget,
        "tariff_windows": body["tariff_windows"],
        "reserved_load_kw": 0,
        "reimbursement_committed_cents": 0,
    })
    db.depots[depot["id"]] = depot
    return ok(out(depot), 201)


@app.route("/fleet/depots/<id_>", methods=["GET"])
def get_depot(id_):
    _uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    depot = get_or_404(db.depots, id_, "ERR_DEPOT_NOT_FOUND")
    return ok(out(depot), 200)


@app.route("/fleet/depots", methods=["GET"])
def list_depots():
    _uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    return list_response(db.depots)


# ---------------------------------------------------------------------------
# Charger
# ---------------------------------------------------------------------------
@app.route("/fleet/chargers", methods=["POST"])
def create_charger():
    _uid, role = authenticate()
    require_roles(role, ["FleetManager"])
    body = get_body()
    require_fields(body, ["depot_id", "name", "connector_type", "max_power_kw"])
    get_or_404(db.depots, body["depot_id"], "ERR_DEPOT_NOT_FOUND")
    if body["connector_type"] not in CONNECTORS:
        raise ApiError("ERR_VALIDATION", 422, "Invalid connector_type.")
    max_power = as_number(body["max_power_kw"], "max_power_kw")
    if max_power <= 0:
        raise ApiError("ERR_VALIDATION", 422, "max_power_kw must be > 0.")
    charger = make_entity({
        "depot_id": body["depot_id"],
        "name": body["name"],
        "connector_type": body["connector_type"],
        "max_power_kw": max_power,
        "service_status": "OPERATIONAL",
    })
    db.chargers[charger["id"]] = charger
    return ok(out(charger), 201)


@app.route("/fleet/chargers/<id_>", methods=["GET"])
def get_charger(id_):
    _uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    charger = get_or_404(db.chargers, id_, "ERR_CHARGER_NOT_FOUND")
    return ok(out(charger), 200)


@app.route("/fleet/chargers", methods=["GET"])
def list_chargers():
    _uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    return list_response(db.chargers, {"depot_id": request.args.get("depot_id")})


# ---------------------------------------------------------------------------
# Vehicle
# ---------------------------------------------------------------------------
@app.route("/fleet/vehicles", methods=["POST"])
def create_vehicle():
    _uid, role = authenticate()
    require_roles(role, ["FleetManager"])
    body = get_body()
    require_fields(body, ["depot_id", "vin", "connector_type",
                          "battery_capacity_kwh", "efficiency_kwh_per_km", "current_soc_pct"])
    get_or_404(db.depots, body["depot_id"], "ERR_DEPOT_NOT_FOUND")
    if body["connector_type"] not in CONNECTORS:
        raise ApiError("ERR_VALIDATION", 422, "Invalid connector_type.")
    battery = as_number(body["battery_capacity_kwh"], "battery_capacity_kwh")
    eff = as_number(body["efficiency_kwh_per_km"], "efficiency_kwh_per_km")
    if battery <= 0:
        raise ApiError("ERR_VALIDATION", 422, "battery_capacity_kwh must be > 0.")
    if eff <= 0:
        raise ApiError("ERR_VALIDATION", 422, "efficiency_kwh_per_km must be > 0.")
    soc = check_soc(body["current_soc_pct"], "current_soc_pct")
    vehicle = make_entity({
        "depot_id": body["depot_id"],
        "vin": body["vin"],
        "connector_type": body["connector_type"],
        "battery_capacity_kwh": battery,
        "efficiency_kwh_per_km": eff,
        "current_soc_pct": soc,
        "odometer_km": 0,
        "status": "IN_SERVICE",
        "readiness_status": "NOT_READY",
    })
    vehicle["readiness_status"] = calc.readiness(vehicle)
    db.vehicles[vehicle["id"]] = vehicle
    return ok(out(vehicle), 201)


@app.route("/fleet/vehicles/<id_>", methods=["GET"])
def get_vehicle(id_):
    _uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    vehicle = get_or_404(db.vehicles, id_, "ERR_VEHICLE_NOT_FOUND")
    return ok(out(vehicle), 200)


@app.route("/fleet/vehicles", methods=["GET"])
def list_vehicles():
    _uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    return list_response(db.vehicles, {"depot_id": request.args.get("depot_id")})


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------
def _revert_assigned_routes(vehicle_id):
    for route in db.route_assignments.values():
        if route["vehicle_id"] == vehicle_id and route["status"] == "ASSIGNED":
            route["status"] = "PLANNED"
            touch(route)


@app.route("/fleet/vehicles/<id_>/telemetry", methods=["POST"])
def ingest_telemetry(id_):
    _uid, role = authenticate()
    require_roles(role, ["DepotOperator"])
    vehicle = get_or_404(db.vehicles, id_, "ERR_VEHICLE_NOT_FOUND")
    body = get_body()
    require_fields(body, ["soc_pct", "odometer_km"])
    soc = check_soc(body["soc_pct"], "soc_pct")
    odo = as_number(body["odometer_km"], "odometer_km")
    if odo < 0:
        raise ApiError("ERR_VALIDATION", 422, "odometer_km must be >= 0.")
    reading_time = db.now()
    if body.get("reading_time") is not None:
        try:
            reading_time = db.parse_dt(body["reading_time"])
        except Exception:
            raise ApiError("ERR_VALIDATION", 422, "Invalid reading_time.")

    reading = make_entity({
        "vehicle_id": id_,
        "soc_pct": soc,
        "odometer_km": odo,
        "reading_time": reading_time,
    }, common=False)
    db.telemetry_readings[reading["id"]] = reading

    vehicle["current_soc_pct"] = soc
    vehicle["odometer_km"] = odo
    vehicle["readiness_status"] = calc.readiness(vehicle)
    touch(vehicle)
    if vehicle["readiness_status"] == "NOT_READY":
        _revert_assigned_routes(vehicle["id"])
    return ok(out(reading), 201)


@app.route("/fleet/vehicles/<id_>/telemetry", methods=["GET"])
def list_telemetry(id_):
    _uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    get_or_404(db.vehicles, id_, "ERR_VEHICLE_NOT_FOUND")
    items = [r for r in db.telemetry_readings.values() if r["vehicle_id"] == id_]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok([out(e) for e in page], 200, is_list=True, pagination=meta)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
@app.route("/fleet/drivers", methods=["POST"])
def create_driver():
    _uid, role = authenticate()
    require_roles(role, ["FleetManager"])
    body = get_body()
    require_fields(body, ["depot_id", "name", "email", "home_tariff_cents_per_kwh"])
    get_or_404(db.depots, body["depot_id"], "ERR_DEPOT_NOT_FOUND")
    tariff = as_number(body["home_tariff_cents_per_kwh"], "home_tariff_cents_per_kwh")
    if tariff < 0:
        raise ApiError("ERR_VALIDATION", 422, "home_tariff_cents_per_kwh must be >= 0.")
    driver = make_entity({
        "depot_id": body["depot_id"],
        "name": body["name"],
        "email": body["email"],
        "home_tariff_cents_per_kwh": tariff,
    })
    db.drivers[driver["id"]] = driver
    return ok(out(driver), 201)


@app.route("/fleet/drivers/<id_>", methods=["GET"])
def get_driver(id_):
    _uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    driver = get_or_404(db.drivers, id_, "ERR_DRIVER_NOT_FOUND")
    return ok(out(driver), 200)


@app.route("/fleet/drivers", methods=["GET"])
def list_drivers():
    _uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    return list_response(db.drivers, {"depot_id": request.args.get("depot_id")})


# ---------------------------------------------------------------------------
# ChargeSession
# ---------------------------------------------------------------------------
def _release_reserved(depot, power):
    depot["reserved_load_kw"] = depot["reserved_load_kw"] - power


@app.route("/fleet/charge-sessions", methods=["POST"])
def create_session():
    _uid, role = authenticate()
    require_roles(role, ["DepotOperator"])
    body = get_body()
    # required-field presence (structural) before existence of referenced FKs
    require_fields(body, ["depot_id", "charger_id", "vehicle_id", "scheduled_start",
                          "scheduled_end", "target_soc_pct", "power_kw",
                          "expected_depot_version"])
    # existence (path FKs in declaration order)
    depot = get_or_404(db.depots, body["depot_id"], "ERR_DEPOT_NOT_FOUND")
    charger = get_or_404(db.chargers, body["charger_id"], "ERR_CHARGER_NOT_FOUND")
    vehicle = get_or_404(db.vehicles, body["vehicle_id"], "ERR_VEHICLE_NOT_FOUND")
    # structural ranges / parsing
    target_soc = check_soc(body["target_soc_pct"], "target_soc_pct")
    power = as_number(body["power_kw"], "power_kw")
    if power <= 0:
        raise ApiError("ERR_VALIDATION", 422, "power_kw must be > 0.")
    if not isinstance(body["expected_depot_version"], int) or isinstance(body["expected_depot_version"], bool):
        raise ApiError("ERR_VALIDATION", 422, "expected_depot_version must be an integer.")
    try:
        sched_start = db.parse_dt(body["scheduled_start"])
        sched_end = db.parse_dt(body["scheduled_end"])
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "Invalid scheduled_start/scheduled_end.")

    # referential checks
    if charger["connector_type"] != vehicle["connector_type"]:
        raise ApiError("ERR_CONNECTOR_INCOMPATIBLE", 422, "Charger/vehicle connector mismatch.")
    if power > charger["max_power_kw"]:
        raise ApiError("ERR_POWER_EXCEEDS_CHARGER", 422, "power_kw exceeds charger max_power_kw.")

    # temporal checks (charger before vehicle)
    charger_sessions = [s for s in db.charge_sessions.values()
                        if s["charger_id"] == charger["id"] and s["status"] in ("SCHEDULED", "ACTIVE")]
    if calc.charger_conflict(sched_start, sched_end, charger_sessions):
        raise ApiError("ERR_CHARGER_TIME_CONFLICT", 409, "Charger time conflict.")
    vehicle_sessions = [s for s in db.charge_sessions.values()
                        if s["vehicle_id"] == vehicle["id"] and s["status"] in ("SCHEDULED", "ACTIVE")]
    if calc.vehicle_conflict(sched_start, sched_end, vehicle_sessions):
        raise ApiError("ERR_VEHICLE_TIME_CONFLICT", 409, "Vehicle time conflict.")

    # fiscal capacity gate
    if depot["reserved_load_kw"] + power > depot["max_load_kw"]:
        raise ApiError("ERR_DEPOT_CAPACITY_EXCEEDED", 409, "Depot capacity exceeded.")

    # OCC (last)
    if body["expected_depot_version"] != depot["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale depot version.")

    estimated = calc.estimated_cost_cents(vehicle, target_soc, depot["tariff_windows"], sched_start)
    session = make_entity({
        "depot_id": depot["id"],
        "charger_id": charger["id"],
        "vehicle_id": vehicle["id"],
        "scheduled_start": sched_start,
        "scheduled_end": sched_end,
        "target_soc_pct": target_soc,
        "power_kw": power,
        "start_soc_pct": None,
        "end_soc_pct": None,
        "actual_start": None,
        "actual_end": None,
        "energy_kwh_delivered": 0,
        "estimated_cost_cents": estimated,
        "final_cost_cents": 0,
        "status": "SCHEDULED",
    })
    db.charge_sessions[session["id"]] = session
    depot["reserved_load_kw"] = depot["reserved_load_kw"] + power
    touch(depot)  # OCC write: bump Depot.version + updated_at
    return ok(out(session), 201)


@app.route("/fleet/charge-sessions/<id_>", methods=["GET"])
def get_session(id_):
    _uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    session = get_or_404(db.charge_sessions, id_, "ERR_SESSION_NOT_FOUND")
    return ok(out(session), 200)


@app.route("/fleet/charge-sessions", methods=["GET"])
def list_sessions():
    _uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    filters = {
        "depot_id": request.args.get("depot_id"),
        "charger_id": request.args.get("charger_id"),
        "vehicle_id": request.args.get("vehicle_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.charge_sessions, filters)


@app.route("/fleet/charge-sessions/<id_>/start", methods=["POST"])
def start_session(id_):
    _uid, role = authenticate()
    require_roles(role, ["DepotOperator"])
    session = get_or_404(db.charge_sessions, id_, "ERR_SESSION_NOT_FOUND")
    body = get_body()
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_NOT_SCHEDULED", 409, "Session not SCHEDULED.")
    charger = db.chargers.get(session["charger_id"])
    if charger is None or charger["service_status"] != "OPERATIONAL":
        raise ApiError("ERR_CHARGER_DOWN", 409, "Charger not OPERATIONAL.")
    actual_start = db.now()
    if body.get("actual_start") is not None:
        try:
            actual_start = db.parse_dt(body["actual_start"])
        except Exception:
            raise ApiError("ERR_VALIDATION", 422, "Invalid actual_start.")
    vehicle = db.vehicles.get(session["vehicle_id"])
    session["start_soc_pct"] = vehicle["current_soc_pct"]
    session["actual_start"] = actual_start
    session["status"] = "ACTIVE"
    touch(session)
    return ok(out(session), 200)


@app.route("/fleet/charge-sessions/<id_>/complete", methods=["POST"])
def complete_session(id_):
    _uid, role = authenticate()
    require_roles(role, ["DepotOperator"])
    session = get_or_404(db.charge_sessions, id_, "ERR_SESSION_NOT_FOUND")
    body = get_body()
    require_fields(body, ["end_soc_pct"])
    end_soc = check_soc(body["end_soc_pct"], "end_soc_pct")
    if session["status"] != "ACTIVE":
        raise ApiError("ERR_SESSION_NOT_ACTIVE", 409, "Session not ACTIVE.")
    if end_soc < session["start_soc_pct"]:
        raise ApiError("ERR_VALIDATION", 422, "end_soc_pct must be >= start_soc_pct.")
    actual_end = db.now()
    if body.get("actual_end") is not None:
        try:
            actual_end = db.parse_dt(body["actual_end"])
        except Exception:
            raise ApiError("ERR_VALIDATION", 422, "Invalid actual_end.")

    depot = db.depots.get(session["depot_id"])
    vehicle = db.vehicles.get(session["vehicle_id"])
    energy = calc.energy_kwh(session["start_soc_pct"], end_soc, vehicle["battery_capacity_kwh"])
    final_cost = calc.final_cost_cents(energy, depot["tariff_windows"],
                                       session["actual_start"], actual_end)
    session["end_soc_pct"] = end_soc
    session["actual_end"] = actual_end
    session["energy_kwh_delivered"] = energy
    session["final_cost_cents"] = final_cost
    session["status"] = "COMPLETED"
    touch(session)

    vehicle["current_soc_pct"] = end_soc
    vehicle["readiness_status"] = calc.readiness(vehicle)
    touch(vehicle)
    _release_reserved(depot, session["power_kw"])
    return ok(out(session), 200)


@app.route("/fleet/charge-sessions/<id_>/cancel", methods=["POST"])
def cancel_session(id_):
    _uid, role = authenticate()
    require_roles(role, ["DepotOperator"])
    session = get_or_404(db.charge_sessions, id_, "ERR_SESSION_NOT_FOUND")
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_NOT_SCHEDULED", 409, "Session not SCHEDULED.")
    depot = db.depots.get(session["depot_id"])
    session["status"] = "CANCELLED"
    touch(session)
    _release_reserved(depot, session["power_kw"])
    return ok(out(session), 200)


# ---------------------------------------------------------------------------
# MaintenanceWorkOrder
# ---------------------------------------------------------------------------
def _interrupt_active_sessions_on_charger(charger_id):
    depot_cache = {}
    for s in db.charge_sessions.values():
        if s["charger_id"] == charger_id and s["status"] == "ACTIVE":
            s["end_soc_pct"] = s["start_soc_pct"]
            s["energy_kwh_delivered"] = 0
            s["final_cost_cents"] = 0
            s["actual_end"] = db.now()
            s["status"] = "INTERRUPTED"
            touch(s)
            depot = db.depots.get(s["depot_id"])
            if depot is not None:
                _release_reserved(depot, s["power_kw"])
            vehicle = db.vehicles.get(s["vehicle_id"])
            if vehicle is not None:
                vehicle["readiness_status"] = calc.readiness(vehicle)
                touch(vehicle)


@app.route("/fleet/work-orders", methods=["POST"])
def create_work_order():
    _uid, role = authenticate()
    require_roles(role, ["DepotOperator", "MaintenanceTech"])
    body = get_body()
    require_fields(body, ["asset_type", "issue", "severity"])
    charger_id = body.get("charger_id")
    vehicle_id = body.get("vehicle_id")
    # existence of provided FK ids (declaration order: charger_id then vehicle_id)
    if charger_id is not None:
        get_or_404(db.chargers, charger_id, "ERR_CHARGER_NOT_FOUND")
    if vehicle_id is not None:
        get_or_404(db.vehicles, vehicle_id, "ERR_VEHICLE_NOT_FOUND")
    asset_type = body["asset_type"]
    if asset_type not in ("CHARGER", "VEHICLE"):
        raise ApiError("ERR_VALIDATION", 422, "Invalid asset_type.")
    if body["severity"] not in SEVERITIES:
        raise ApiError("ERR_VALIDATION", 422, "Invalid severity.")
    # asset target match
    if asset_type == "CHARGER":
        if charger_id is None or vehicle_id is not None:
            raise ApiError("ERR_ASSET_TARGET_INVALID", 422, "CHARGER order requires charger_id only.")
    else:  # VEHICLE
        if vehicle_id is None or charger_id is not None:
            raise ApiError("ERR_ASSET_TARGET_INVALID", 422, "VEHICLE order requires vehicle_id only.")

    wo = make_entity({
        "asset_type": asset_type,
        "charger_id": charger_id,
        "vehicle_id": vehicle_id,
        "issue": body["issue"],
        "severity": body["severity"],
        "status": "OPEN",
        "opened_at": db.now(),
        "resolved_at": None,
        "downtime_minutes": 0,
    })
    db.work_orders[wo["id"]] = wo

    if asset_type == "CHARGER":
        charger = db.chargers[charger_id]
        charger["service_status"] = "DOWN"
        touch(charger)
        _interrupt_active_sessions_on_charger(charger_id)
    else:
        vehicle = db.vehicles[vehicle_id]
        vehicle["status"] = "GROUNDED"
        vehicle["readiness_status"] = "NOT_READY"
        touch(vehicle)
        _revert_assigned_routes(vehicle_id)
    return ok(out(wo), 201)


@app.route("/fleet/work-orders/<id_>", methods=["GET"])
def get_work_order(id_):
    _uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    wo = get_or_404(db.work_orders, id_, "ERR_WORK_ORDER_NOT_FOUND")
    return ok(out(wo), 200)


@app.route("/fleet/work-orders", methods=["GET"])
def list_work_orders():
    _uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    filters = {
        "charger_id": request.args.get("charger_id"),
        "vehicle_id": request.args.get("vehicle_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.work_orders, filters)


_WO_EDGES = {
    ("OPEN", "IN_PROGRESS"),
    ("IN_PROGRESS", "ON_HOLD"),
    ("ON_HOLD", "IN_PROGRESS"),
    ("IN_PROGRESS", "RESOLVED"),
    ("RESOLVED", "CLOSED"),
}
_WO_STATES = {"OPEN", "IN_PROGRESS", "ON_HOLD", "RESOLVED", "CLOSED"}


def _asset_has_other_open_wo(wo):
    for other in db.work_orders.values():
        if other["id"] == wo["id"]:
            continue
        if other["asset_type"] != wo["asset_type"]:
            continue
        if wo["asset_type"] == "CHARGER" and other["charger_id"] != wo["charger_id"]:
            continue
        if wo["asset_type"] == "VEHICLE" and other["vehicle_id"] != wo["vehicle_id"]:
            continue
        if other["status"] != "CLOSED":
            return True
    return False


@app.route("/fleet/work-orders/<id_>/transition", methods=["POST"])
def transition_work_order(id_):
    _uid, role = authenticate()
    require_roles(role, ["MaintenanceTech"])
    wo = get_or_404(db.work_orders, id_, "ERR_WORK_ORDER_NOT_FOUND")
    body = get_body()
    require_fields(body, ["target_status"])
    target = body["target_status"]
    if target not in _WO_STATES:
        raise ApiError("ERR_VALIDATION", 422, "Invalid target_status.")
    if (wo["status"], target) not in _WO_EDGES:
        raise ApiError("ERR_WORK_ORDER_INVALID_TRANSITION", 409, "Illegal work order transition.")

    wo["status"] = target
    if target == "RESOLVED":
        wo["resolved_at"] = db.now()
        elapsed = (wo["resolved_at"] - wo["opened_at"]).total_seconds()
        wo["downtime_minutes"] = int(elapsed // 60)
        if not _asset_has_other_open_wo(wo):
            if wo["asset_type"] == "CHARGER":
                charger = db.chargers.get(wo["charger_id"])
                if charger is not None:
                    charger["service_status"] = "OPERATIONAL"
                    touch(charger)
            else:
                vehicle = db.vehicles.get(wo["vehicle_id"])
                if vehicle is not None:
                    vehicle["status"] = "IN_SERVICE"
                    vehicle["readiness_status"] = calc.readiness(vehicle)
                    touch(vehicle)
    touch(wo)
    return ok(out(wo), 200)


# ---------------------------------------------------------------------------
# RouteAssignment
# ---------------------------------------------------------------------------
@app.route("/fleet/route-assignments", methods=["POST"])
def create_route():
    _uid, role = authenticate()
    require_roles(role, ["FleetManager", "DepotOperator"])
    body = get_body()
    require_fields(body, ["depot_id", "vehicle_id", "driver_id", "route_name",
                          "distance_km", "required_soc_pct", "scheduled_departure"])
    get_or_404(db.depots, body["depot_id"], "ERR_DEPOT_NOT_FOUND")
    get_or_404(db.vehicles, body["vehicle_id"], "ERR_VEHICLE_NOT_FOUND")
    get_or_404(db.drivers, body["driver_id"], "ERR_DRIVER_NOT_FOUND")
    distance = as_number(body["distance_km"], "distance_km")
    if distance <= 0:
        raise ApiError("ERR_VALIDATION", 422, "distance_km must be > 0.")
    required_soc = check_soc(body["required_soc_pct"], "required_soc_pct")
    try:
        departure = db.parse_dt(body["scheduled_departure"])
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "Invalid scheduled_departure.")
    route = make_entity({
        "depot_id": body["depot_id"],
        "vehicle_id": body["vehicle_id"],
        "driver_id": body["driver_id"],
        "route_name": body["route_name"],
        "distance_km": distance,
        "required_soc_pct": required_soc,
        "scheduled_departure": departure,
        "status": "PLANNED",
    })
    db.route_assignments[route["id"]] = route
    return ok(out(route), 201)


@app.route("/fleet/route-assignments/<id_>", methods=["GET"])
def get_route(id_):
    _uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    route = get_or_404(db.route_assignments, id_, "ERR_ROUTE_NOT_FOUND")
    return ok(out(route), 200)


@app.route("/fleet/route-assignments", methods=["GET"])
def list_routes():
    _uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    filters = {
        "depot_id": request.args.get("depot_id"),
        "vehicle_id": request.args.get("vehicle_id"),
        "driver_id": request.args.get("driver_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.route_assignments, filters)


@app.route("/fleet/route-assignments/<id_>/assign", methods=["POST"])
def assign_route(id_):
    _uid, role = authenticate()
    require_roles(role, ["DepotOperator"])
    route = get_or_404(db.route_assignments, id_, "ERR_ROUTE_NOT_FOUND")
    if route["status"] != "PLANNED":
        raise ApiError("ERR_ROUTE_NOT_PLANNED", 409, "Route not PLANNED.")
    vehicle = db.vehicles.get(route["vehicle_id"])
    if vehicle["status"] == "GROUNDED":
        raise ApiError("ERR_VEHICLE_GROUNDED", 409, "Vehicle is GROUNDED.")
    if vehicle["readiness_status"] != "READY":
        raise ApiError("ERR_VEHICLE_NOT_READY", 409, "Vehicle not READY.")
    if vehicle["current_soc_pct"] < route["required_soc_pct"]:
        raise ApiError("ERR_SOC_BELOW_ROUTE_REQUIREMENT", 409, "SOC below route requirement.")
    route["status"] = "ASSIGNED"
    touch(route)
    return ok(out(route), 200)


@app.route("/fleet/route-assignments/<id_>/unassign", methods=["POST"])
def unassign_route(id_):
    _uid, role = authenticate()
    require_roles(role, ["DepotOperator"])
    route = get_or_404(db.route_assignments, id_, "ERR_ROUTE_NOT_FOUND")
    if route["status"] != "ASSIGNED":
        raise ApiError("ERR_ROUTE_NOT_ASSIGNED", 409, "Route not ASSIGNED.")
    route["status"] = "PLANNED"
    touch(route)
    return ok(out(route), 200)


@app.route("/fleet/route-assignments/<id_>/complete", methods=["POST"])
def complete_route(id_):
    _uid, role = authenticate()
    require_roles(role, ["DepotOperator"])
    route = get_or_404(db.route_assignments, id_, "ERR_ROUTE_NOT_FOUND")
    if route["status"] != "ASSIGNED":
        raise ApiError("ERR_ROUTE_NOT_ASSIGNED", 409, "Route not ASSIGNED.")
    route["status"] = "COMPLETED"
    touch(route)
    return ok(out(route), 200)


# ---------------------------------------------------------------------------
# ReimbursementClaim
# ---------------------------------------------------------------------------
def _valid_period_month(value):
    return isinstance(value, str) and len(value) == 7 and value[4] == "-" \
        and value[:4].isdigit() and value[5:].isdigit() \
        and 1 <= int(value[5:]) <= 12


@app.route("/fleet/reimbursement-claims", methods=["POST"])
def create_claim():
    uid, role = authenticate()
    require_roles(role, ["Driver"])
    body = get_body()
    # driver ownership (authz) takes precedence over structural/existence
    did = body.get("driver_id")
    if did is not None and str(did) != str(uid):
        raise ApiError("ERR_UNAUTHORIZED", 403, "Driver may only file own claims.")
    require_fields(body, ["driver_id", "depot_id", "period_month", "kwh_claimed",
                          "odometer_start", "odometer_end", "expected_depot_version"])
    # existence (declaration order: driver_id, depot_id)
    driver = get_or_404(db.drivers, body["driver_id"], "ERR_DRIVER_NOT_FOUND")
    depot = get_or_404(db.depots, body["depot_id"], "ERR_DEPOT_NOT_FOUND")
    # structural
    if not _valid_period_month(body["period_month"]):
        raise ApiError("ERR_VALIDATION", 422, "period_month must be 'YYYY-MM'.")
    kwh = as_number(body["kwh_claimed"], "kwh_claimed")
    if kwh <= 0:
        raise ApiError("ERR_VALIDATION", 422, "kwh_claimed must be > 0.")
    as_number(body["odometer_start"], "odometer_start")
    as_number(body["odometer_end"], "odometer_end")
    if not isinstance(body["expected_depot_version"], int) or isinstance(body["expected_depot_version"], bool):
        raise ApiError("ERR_VALIDATION", 422, "expected_depot_version must be an integer.")

    estimated = calc.reimbursement_cents(kwh, driver["home_tariff_cents_per_kwh"])
    # fiscal budget gate
    if depot["reimbursement_committed_cents"] + estimated > depot["reimbursement_budget_cents"]:
        raise ApiError("ERR_REIMBURSEMENT_BUDGET_EXCEEDED", 409, "Reimbursement budget exceeded.")
    # OCC (last)
    if body["expected_depot_version"] != depot["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale depot version.")

    claim = make_entity({
        "driver_id": driver["id"],
        "depot_id": depot["id"],
        "period_month": body["period_month"],
        "kwh_claimed": kwh,
        "odometer_start": body["odometer_start"],
        "odometer_end": body["odometer_end"],
        "metered_kwh_verified": None,
        "committed_amount_cents": estimated,
        "estimated_amount_cents": estimated,
        "final_amount_cents": 0,
        "approved_by_user_id": None,
        "status": "SUBMITTED",
    })
    db.reimbursement_claims[claim["id"]] = claim
    depot["reimbursement_committed_cents"] += estimated
    touch(depot)  # OCC write: bump Depot.version + updated_at
    return ok(out(claim), 201)


@app.route("/fleet/reimbursement-claims/<id_>", methods=["GET"])
def get_claim(id_):
    _uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    claim = get_or_404(db.reimbursement_claims, id_, "ERR_CLAIM_NOT_FOUND")
    return ok(out(claim), 200)


@app.route("/fleet/reimbursement-claims", methods=["GET"])
def list_claims():
    _uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    filters = {
        "driver_id": request.args.get("driver_id"),
        "depot_id": request.args.get("depot_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.reimbursement_claims, filters)


@app.route("/fleet/reimbursement-claims/<id_>/review", methods=["POST"])
def review_claim(id_):
    uid, role = authenticate()
    require_roles(role, ["FinanceManager"])
    claim = get_or_404(db.reimbursement_claims, id_, "ERR_CLAIM_NOT_FOUND")
    body = get_body()
    require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in ("APPROVE", "REJECT"):
        raise ApiError("ERR_VALIDATION", 422, "decision must be APPROVE or REJECT.")
    if decision == "APPROVE" and body.get("metered_kwh_verified") is None:
        raise ApiError("ERR_VALIDATION", 422, "metered_kwh_verified required to approve.")
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_SUBMITTED", 409, "Claim not SUBMITTED.")

    depot = db.depots.get(claim["depot_id"])
    if decision == "APPROVE":
        metered = as_number(body["metered_kwh_verified"], "metered_kwh_verified")
        driver = db.drivers.get(claim["driver_id"])
        final = calc.reimbursement_cents(metered, driver["home_tariff_cents_per_kwh"])
        claim["metered_kwh_verified"] = metered
        claim["final_amount_cents"] = final
        depot["reimbursement_committed_cents"] += (final - claim["estimated_amount_cents"])
        claim["committed_amount_cents"] = final
        claim["approved_by_user_id"] = uid
        claim["status"] = "APPROVED"
    else:
        depot["reimbursement_committed_cents"] -= claim["committed_amount_cents"]
        claim["committed_amount_cents"] = 0
        claim["status"] = "REJECTED"
    touch(claim)
    return ok(out(claim), 200)


@app.route("/fleet/reimbursement-claims/<id_>/pay", methods=["POST"])
def pay_claim(id_):
    uid, role = authenticate()
    require_roles(role, ["FinanceManager"])
    claim = get_or_404(db.reimbursement_claims, id_, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "APPROVED":
        raise ApiError("ERR_CLAIM_NOT_APPROVED", 409, "Claim not APPROVED.")
    if str(uid) == str(claim["approved_by_user_id"]):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403, "Payer must differ from approver.")
    depot = db.depots.get(claim["depot_id"])
    depot["reimbursement_committed_cents"] -= claim["committed_amount_cents"]
    claim["committed_amount_cents"] = 0
    claim["status"] = "PAID"
    touch(claim)
    return ok(out(claim), 200)


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------
@app.route("/fleet/invoices", methods=["POST"])
def create_invoice():
    _uid, role = authenticate()
    require_roles(role, ["FleetManager"])
    body = get_body()
    require_fields(body, ["depot_id", "period_month"])
    depot = get_or_404(db.depots, body["depot_id"], "ERR_DEPOT_NOT_FOUND")
    if not _valid_period_month(body["period_month"]):
        raise ApiError("ERR_VALIDATION", 422, "period_month must be 'YYYY-MM'.")
    period = body["period_month"]
    for inv in db.invoices.values():
        if inv["depot_id"] == depot["id"] and inv["period_month"] == period:
            raise ApiError("ERR_DUPLICATE_INVOICE", 409, "Invoice already exists for depot/month.")
    figures = calc.invoice_figures(depot, period)
    invoice = make_entity({
        "depot_id": depot["id"],
        "period_month": period,
        "energy_subtotal_cents": figures["energy_subtotal_cents"],
        "peak_demand_kw": figures["peak_demand_kw"],
        "demand_charge_cents": figures["demand_charge_cents"],
        "total_cents": figures["total_cents"],
        "status": "DRAFT",
    })
    db.invoices[invoice["id"]] = invoice
    return ok(out(invoice), 201)


@app.route("/fleet/invoices/<id_>", methods=["GET"])
def get_invoice(id_):
    _uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    invoice = get_or_404(db.invoices, id_, "ERR_INVOICE_NOT_FOUND")
    return ok(out(invoice), 200)


@app.route("/fleet/invoices", methods=["GET"])
def list_invoices():
    _uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    filters = {
        "depot_id": request.args.get("depot_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.invoices, filters)


@app.route("/fleet/invoices/<id_>/issue", methods=["POST"])
def issue_invoice(id_):
    _uid, role = authenticate()
    require_roles(role, ["FinanceManager"])
    invoice = get_or_404(db.invoices, id_, "ERR_INVOICE_NOT_FOUND")
    if invoice["status"] != "DRAFT":
        raise ApiError("ERR_INVOICE_NOT_DRAFT", 409, "Invoice not DRAFT.")
    invoice["status"] = "ISSUED"
    touch(invoice)
    return ok(out(invoice), 200)


@app.route("/fleet/invoices/<id_>/pay", methods=["POST"])
def pay_invoice(id_):
    _uid, role = authenticate()
    require_roles(role, ["FinanceManager"])
    invoice = get_or_404(db.invoices, id_, "ERR_INVOICE_NOT_FOUND")
    if invoice["status"] != "ISSUED":
        raise ApiError("ERR_INVOICE_NOT_ISSUED", 409, "Invoice not ISSUED.")
    invoice["status"] = "PAID"
    touch(invoice)
    return ok(out(invoice), 200)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
