"""Oven station, cooling bay and technician routes (CASCADE-E lives here)."""
from flask import Blueprint

import auth
import core
import rt
import svc
from core import Checks, Store, touch
from errors import fail
from schema import add_schema, body_json, coerce, enum_filter

bp = Blueprint("equip", __name__)

SHOP_READ = ("PlantAdmin", "MoldingOperator", "QualityInspector", "LogisticsPlanner")
TECH_READ = ("PlantAdmin", "MoldingOperator", "AssemblyTechnician",
             "QualityInspector", "LogisticsPlanner")

STATION_CREATE = {
    "station_code": {"type": "string", "required": True, "min_len": 2, "max_len": 32},
    "arm_count": {"type": "int", "required": True, "min": 1, "max": 6},
    "max_size_class": {"type": "enum", "required": True, "values": rt.SIZE_CLASSES},
    "changeover_buffer_min": {"type": "int", "required": True, "min": 0},
    "energy_cents_per_min": {"type": "int", "required": True, "min": 0},
}

BAY_CREATE = {
    "bay_code": {"type": "string", "required": True, "min_len": 2, "max_len": 32},
    "concurrent_slot_capacity": {"type": "int", "required": True, "min": 1},
    "airflow_mode": {"type": "enum", "required": True, "values": rt.AIRFLOW_MODES},
}

DOWN_SPEC = {"down_reason": {"type": "string", "required": True,
                             "min_len": 1, "max_len": 500}}
EMPTY_SPEC = {}


# --------------------------------------------------------------------------
# Oven stations.
# --------------------------------------------------------------------------
@bp.route("/oven-stations", methods=["POST"])
def create_station():
    auth.authenticate(("PlantAdmin",))
    body = body_json()
    checks = Checks()
    add_schema(checks, body, STATION_CREATE)
    checks.add(26, lambda: rt.unique_code("oven_stations", "station_code",
                                          body.get("station_code")))
    checks.run()
    row = coerce(body, STATION_CREATE)
    row["status"] = "OPERATIONAL"
    core.insert("oven_stations", row)
    return rt.one("oven_stations", row, 201)


@bp.route("/oven-stations", methods=["GET"])
def list_stations():
    auth.authenticate(SHOP_READ)
    checks = Checks()
    items = [None]

    def collect():
        rows = core.rows("oven_stations")
        rows = rt.filter_eq(rows, "status", enum_filter("status", rt.EQUIP_STATUSES))
        rows = rt.filter_eq(rows, "max_size_class",
                            enum_filter("max_size_class", rt.SIZE_CLASSES))
        items[0] = rows

    checks.add(21, collect)
    checks.run()
    return rt.many("oven_stations", items[0])


@bp.route("/oven-stations/<oven_station_id>", methods=["GET"])
def read_station(oven_station_id):
    auth.authenticate(SHOP_READ)
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(
        row=rt.find("oven_stations", oven_station_id)))
    checks.run()
    return rt.one("oven_stations", holder["row"])


def _equip_action(collection, row_id, spec, want_status, error_id, priority):
    auth.authenticate(("PlantAdmin",))
    body = body_json()
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(row=rt.find(collection, row_id)))
    add_schema(checks, body, spec)

    def state():
        if holder["row"]["status"] != want_status:
            fail(error_id, "Status is already %s." % holder["row"]["status"])

    checks.add(priority, state)
    return holder, body, checks


@bp.route("/oven-stations/<oven_station_id>/mark-down", methods=["POST"])
def station_mark_down(oven_station_id):
    holder, body, checks = _equip_action(
        "oven_stations", oven_station_id, DOWN_SPEC, "OPERATIONAL",
        "ERR_OVEN_STATION_DOWN", 32)
    checks.run()
    station = holder["row"]
    station["status"] = "DOWN"
    station["down_reason"] = body["down_reason"]
    touch(station)
    svc.abort_scheduled_cycles(
        lambda c: c.get("oven_station_id") == station["id"],
        "STATION_DOWN", "STATION_DOWN")
    svc.sweep_unblock_resin()
    return rt.one("oven_stations", station)


@bp.route("/oven-stations/<oven_station_id>/restore", methods=["POST"])
def station_restore(oven_station_id):
    holder, _body, checks = _equip_action(
        "oven_stations", oven_station_id, EMPTY_SPEC, "DOWN",
        "ERR_OVEN_STATION_ALREADY_OPERATIONAL", 32)
    checks.run()
    station = holder["row"]
    station["status"] = "OPERATIONAL"
    touch(station)
    return rt.one("oven_stations", station)


# --------------------------------------------------------------------------
# Cooling bays.
# --------------------------------------------------------------------------
@bp.route("/cooling-bays", methods=["POST"])
def create_bay():
    auth.authenticate(("PlantAdmin",))
    body = body_json()
    checks = Checks()
    add_schema(checks, body, BAY_CREATE)
    checks.add(26, lambda: rt.unique_code("cooling_bays", "bay_code",
                                          body.get("bay_code")))
    checks.run()
    row = coerce(body, BAY_CREATE)
    row["status"] = "OPERATIONAL"
    core.insert("cooling_bays", row)
    return rt.one("cooling_bays", row, 201)


@bp.route("/cooling-bays", methods=["GET"])
def list_bays():
    auth.authenticate(SHOP_READ)
    checks = Checks()
    items = [None]

    def collect():
        rows = core.rows("cooling_bays")
        rows = rt.filter_eq(rows, "status", enum_filter("status", rt.EQUIP_STATUSES))
        rows = rt.filter_eq(rows, "airflow_mode",
                            enum_filter("airflow_mode", rt.AIRFLOW_MODES))
        items[0] = rows

    checks.add(21, collect)
    checks.run()
    return rt.many("cooling_bays", items[0])


@bp.route("/cooling-bays/<cooling_bay_id>", methods=["GET"])
def read_bay(cooling_bay_id):
    auth.authenticate(SHOP_READ)
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(row=rt.find("cooling_bays", cooling_bay_id)))
    checks.run()
    return rt.one("cooling_bays", holder["row"])


@bp.route("/cooling-bays/<cooling_bay_id>/mark-down", methods=["POST"])
def bay_mark_down(cooling_bay_id):
    holder, body, checks = _equip_action(
        "cooling_bays", cooling_bay_id, DOWN_SPEC, "OPERATIONAL",
        "ERR_COOLING_BAY_DOWN", 33)
    checks.run()
    bay = holder["row"]
    bay["status"] = "DOWN"
    bay["down_reason"] = body["down_reason"]
    touch(bay)
    svc.abort_scheduled_cycles(
        lambda c: c.get("cooling_bay_id") == bay["id"], "BAY_DOWN", "BAY_DOWN")
    svc.sweep_unblock_resin()
    return rt.one("cooling_bays", bay)


@bp.route("/cooling-bays/<cooling_bay_id>/restore", methods=["POST"])
def bay_restore(cooling_bay_id):
    holder, _body, checks = _equip_action(
        "cooling_bays", cooling_bay_id, EMPTY_SPEC, "DOWN",
        "ERR_COOLING_BAY_ALREADY_OPERATIONAL", 33)
    checks.run()
    bay = holder["row"]
    bay["status"] = "OPERATIONAL"
    touch(bay)
    return rt.one("cooling_bays", bay)


# --------------------------------------------------------------------------
# Technicians.
# --------------------------------------------------------------------------
TECH_CREATE = {
    "employee_code": {"type": "string", "required": True, "min_len": 3, "max_len": 32},
    "full_name": {"type": "string", "required": True, "min_len": 1, "max_len": 120},
    "role_code": {"type": "enum", "required": True, "values": rt.ROLE_CODES},
    "certifications": {"type": "array", "required": False, "max_items": 4},
}

SUSPEND_SPEC = {"suspend_reason": {"type": "string", "required": True,
                                   "min_len": 1, "max_len": 500}}


def _check_certifications(body):
    raw = body.get("certifications")
    if raw is None:
        return
    seen = []
    for element in raw:
        if not isinstance(element, str) or element not in rt.CERTIFICATIONS:
            fail("ERR_VALIDATION", "certifications holds an unrecognised element.")
        if element in seen:
            fail("ERR_VALIDATION", "certifications repeats '%s'." % element)
        seen.append(element)


@bp.route("/technicians", methods=["POST"])
def create_technician():
    auth.authenticate(("PlantAdmin",))
    body = body_json()
    checks = Checks()
    add_schema(checks, body, TECH_CREATE)
    checks.add(20.5, lambda: _check_certifications(body))
    checks.add(26, lambda: rt.unique_code("technicians", "employee_code",
                                          body.get("employee_code")))
    checks.run()
    row = coerce(body, TECH_CREATE)
    row["certifications"] = list(body.get("certifications") or [])
    row["status"] = "ACTIVE"
    core.insert("technicians", row)
    return rt.one("technicians", row, 201)


@bp.route("/technicians", methods=["GET"])
def list_technicians():
    auth.authenticate(TECH_READ)
    checks = Checks()
    items = [None]

    def collect():
        rows = core.rows("technicians")
        rows = rt.filter_eq(rows, "role_code", enum_filter("role_code", rt.ROLE_CODES))
        rows = rt.filter_eq(rows, "status", enum_filter("status", rt.PERSON_STATUSES))
        items[0] = rows

    checks.add(21, collect)
    checks.run()
    return rt.many("technicians", items[0])


@bp.route("/technicians/<technician_id>", methods=["GET"])
def read_technician(technician_id):
    auth.authenticate(TECH_READ)
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(row=rt.find("technicians", technician_id)))
    checks.run()
    return rt.one("technicians", holder["row"])


@bp.route("/technicians/<technician_id>/suspend", methods=["POST"])
def suspend_technician(technician_id):
    holder, body, checks = _equip_action(
        "technicians", technician_id, SUSPEND_SPEC, "ACTIVE",
        "ERR_TECHNICIAN_SUSPENDED", 30)
    checks.run()
    tech = holder["row"]
    tech["status"] = "SUSPENDED"
    tech["suspend_reason"] = body["suspend_reason"]
    touch(tech)
    return rt.one("technicians", tech)


@bp.route("/technicians/<technician_id>/reinstate", methods=["POST"])
def reinstate_technician(technician_id):
    holder, _body, checks = _equip_action(
        "technicians", technician_id, EMPTY_SPEC, "SUSPENDED",
        "ERR_TECHNICIAN_ALREADY_ACTIVE", 30.5)
    checks.run()
    tech = holder["row"]
    tech["status"] = "ACTIVE"
    touch(tech)
    return rt.one("technicians", tech)
