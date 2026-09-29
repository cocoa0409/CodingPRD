"""Hydrotreating units, catalyst charges and turnaround windows (PRD 3.3)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import domain
import response
import store
import validate
from constants import TURNAROUND_BUFFER_HOURS, TURNAROUND_SCOPES
from errors import (
    ERR_CATALYST_CHANGE_OUTSIDE_WINDOW,
    ERR_INVALID_REQUEST,
    ERR_INVALID_UNIT_STATE,
    ERR_INVALID_WINDOW_STATE,
    ERR_TURNAROUND_BUFFER_VIOLATION,
    ERR_UNIT_WINDOW_CONFLICT,
    fail,
)
from routes.helpers import find, listing
from store import bump, q

bp = Blueprint("units", __name__)
ZERO = Decimal("0")
BUFFER = timedelta(hours=TURNAROUND_BUFFER_HOURS)
BLOCKING_RUN_STATES = ("PLANNED", "HYDROGEN_SECURED", "RUNNING")


def overlaps(a_start, a_end, b_start, b_end):
    """Half-open intersection: touching endpoints do not intersect."""
    return a_start < b_end and b_start < a_end


@bp.post("/hydrotreating-units")
def create_unit():
    validate.auth("PlantOperator")
    data = validate.body()
    name = validate.get_str(data, "name", 1, 40)
    capacity = validate.get_num(data, "nameplate_capacity_mt_per_day", 0, 6000, 3,
                                exclusive_min=True)
    max_saf = validate.get_num(data, "max_saf_share_pct", 0, 60, 2)
    for existing in store.units.values():
        if existing["name"] == name:
            fail(ERR_INVALID_REQUEST, "Unit name '%s' is already registered." % name)

    row = store.new_row()
    row.update({
        "name": name,
        "nameplate_capacity_mt_per_day": q(capacity, 3),
        "max_saf_share_pct": q(max_saf, 2),
        "status": "IDLE",
        "active_catalyst_charge_id": None,
        "requires_turnaround": False,
    })
    store.units[row["id"]] = row
    return response.ok(row, 201)


@bp.get("/hydrotreating-units/<unit_id>")
def read_unit(unit_id):
    validate.auth("PlantOperator", "ComplianceOfficer")
    return response.ok(find("unit", unit_id))


@bp.get("/hydrotreating-units")
def list_units():
    validate.auth("PlantOperator", "ComplianceOfficer")
    rows, limit, offset = listing(store.table_rows(store.units), {
        "status": "status",
        "active_catalyst_charge_id": "active_catalyst_charge_id",
        "requires_turnaround": "requires_turnaround",
    })
    return response.page(rows, limit, offset)


@bp.post("/hydrotreating-units/<unit_id>/catalyst-charges")
def install_charge(unit_id):
    validate.auth("PlantOperator")
    unit = find("unit", unit_id)
    data = validate.body()
    design = validate.get_num(data, "design_throughput_mt", 0, 2000000, 3,
                              exclusive_min=True)
    installed_at = validate.get_dt(data, "installed_at")

    incumbent = None
    if unit["active_catalyst_charge_id"]:
        candidate = store.charges.get(unit["active_catalyst_charge_id"])
        if candidate is not None and candidate["status"] in ("ACTIVE", "DERATED", "SPENT"):
            incumbent = candidate
    if incumbent is not None and unit["status"] != "DOWN_TURNAROUND":
        fail(ERR_INVALID_UNIT_STATE,
             "A catalyst swap requires the unit to be DOWN_TURNAROUND.")

    authorized = False
    for window in domain.unit_windows(unit["id"]):
        if window["scope"] != "CATALYST_CHANGE":
            continue
        if window["status"] not in ("APPROVED", "IN_PROGRESS"):
            continue
        if window["start_at"] <= installed_at < window["end_at"]:
            authorized = True
            break
    if not authorized:
        fail(ERR_CATALYST_CHANGE_OUTSIDE_WINDOW,
             "installed_at must fall inside an APPROVED or IN_PROGRESS CATALYST_CHANGE window.")

    row = store.new_row()
    row.update({
        "unit_id": unit["id"],
        "design_throughput_mt": q(design, 3),
        "installed_at": installed_at,
        "cumulative_throughput_mt": q(ZERO, 3),
        "activity_index": q(Decimal("1"), 4),
        "status": "ACTIVE",
    })
    store.charges[row["id"]] = row

    if incumbent is not None:
        incumbent["status"] = "REMOVED"
        bump(incumbent)

    unit["active_catalyst_charge_id"] = row["id"]
    unit["requires_turnaround"] = False
    bump(unit)
    return response.ok(row, 201)


@bp.get("/hydrotreating-units/<unit_id>/catalyst-charges")
def list_charges(unit_id):
    validate.auth("PlantOperator", "ComplianceOfficer")
    unit = find("unit", unit_id)
    rows, limit, offset = listing(domain.unit_charges(unit["id"]), {"status": "status"})
    return response.page(rows, limit, offset)


@bp.post("/hydrotreating-units/<unit_id>/turnaround-windows")
def plan_window(unit_id):
    validate.auth("PlantOperator")
    unit = find("unit", unit_id)
    data = validate.body()
    scope = validate.get_enum(data, "scope", TURNAROUND_SCOPES)
    start_at = validate.get_dt(data, "start_at")
    end_at = validate.get_dt(data, "end_at")
    if end_at <= start_at:
        fail(ERR_INVALID_REQUEST, "Field 'end_at' must be strictly after 'start_at'.")

    for other in domain.unit_windows(unit["id"]):
        if other["status"] in ("CANCELLED", "COMPLETED"):
            continue
        before = start_at - other["end_at"]
        after = other["start_at"] - end_at
        if before >= BUFFER or after >= BUFFER:
            continue
        fail(ERR_TURNAROUND_BUFFER_VIOLATION,
             "A turnaround window needs at least 72 hours of clearance on both sides.")

    row = store.new_row()
    row.update({
        "unit_id": unit["id"],
        "scope": scope,
        "start_at": start_at,
        "end_at": end_at,
        "status": "PLANNED",
    })
    store.windows[row["id"]] = row
    return response.ok(row, 201)


@bp.get("/hydrotreating-units/<unit_id>/turnaround-windows")
def list_windows(unit_id):
    validate.auth("PlantOperator", "ComplianceOfficer")
    unit = find("unit", unit_id)
    rows, limit, offset = listing(domain.unit_windows(unit["id"]),
                                  {"status": "status", "scope": "scope"})
    return response.page(rows, limit, offset)


@bp.post("/turnaround-windows/<window_id>/approvals")
def approve_window(window_id):
    validate.auth("PlantOperator")
    window = find("window", window_id)
    if window["status"] != "PLANNED":
        fail(ERR_INVALID_WINDOW_STATE,
             "Only a PLANNED window may be approved; this one is %s." % window["status"])
    for run in domain.unit_runs(window["unit_id"]):
        if run["status"] not in BLOCKING_RUN_STATES:
            continue
        if overlaps(window["start_at"], window["end_at"],
                    run["window_start"], run["window_end"]):
            fail(ERR_UNIT_WINDOW_CONFLICT,
                 "A campaign on this unit intersects the window interval.")
    window["status"] = "APPROVED"
    bump(window)
    return response.ok(window)


@bp.post("/turnaround-windows/<window_id>/starts")
def start_window(window_id):
    validate.auth("PlantOperator")
    window = find("window", window_id)
    if window["status"] != "APPROVED":
        fail(ERR_INVALID_WINDOW_STATE,
             "Only an APPROVED window may be started; this one is %s." % window["status"])
    clock = store.now()
    if not (window["start_at"] <= clock < window["end_at"]):
        fail(ERR_INVALID_WINDOW_STATE,
             "The logical clock is outside the window's half-open interval.")
    unit = store.units.get(window["unit_id"])
    if unit is None or unit["status"] != "IDLE":
        fail(ERR_INVALID_UNIT_STATE, "The unit must be IDLE to be taken down.")
    window["status"] = "IN_PROGRESS"
    bump(window)
    unit["status"] = "DOWN_TURNAROUND"
    bump(unit)
    return response.ok(window)


@bp.post("/turnaround-windows/<window_id>/completions")
def complete_window(window_id):
    validate.auth("PlantOperator")
    window = find("window", window_id)
    if window["status"] != "IN_PROGRESS":
        fail(ERR_INVALID_WINDOW_STATE,
             "Only an IN_PROGRESS window may be completed; this one is %s." % window["status"])
    window["status"] = "COMPLETED"
    bump(window)
    unit = store.units.get(window["unit_id"])
    if unit is not None:
        unit["status"] = "IDLE"
        charge = store.charges.get(unit["active_catalyst_charge_id"]) \
            if unit["active_catalyst_charge_id"] else None
        if charge is not None and charge["status"] == "ACTIVE":
            unit["requires_turnaround"] = False
        bump(unit)
    return response.ok(window)


@bp.post("/turnaround-windows/<window_id>/cancellations")
def cancel_window(window_id):
    validate.auth("PlantOperator")
    window = find("window", window_id)
    data = validate.body()
    validate.get_str(data, "reason", 1, 500)
    if window["status"] not in ("PLANNED", "APPROVED"):
        fail(ERR_INVALID_WINDOW_STATE,
             "Only a PLANNED or APPROVED window may be cancelled; this one is %s."
             % window["status"])
    window["status"] = "CANCELLED"
    bump(window)
    return response.ok(window)
