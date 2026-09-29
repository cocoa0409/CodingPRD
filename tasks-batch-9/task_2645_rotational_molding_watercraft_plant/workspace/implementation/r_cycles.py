"""Molding cycle routes: three distinct interval semantics, mould selection,
CASCADE-A (abort) and CASCADE-B (demould)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import core
import rt
import svc
from core import Checks, S, ZERO, floor_int, q2, q3, touch
from errors import fail
from schema import (add_schema, body_json, coerce, enum_filter, str_filter,
                    ts_filter)

bp = Blueprint("cycles", __name__)

CYCLE_READ = ("PlantAdmin", "MoldingOperator", "ResinTechnician",
              "QualityInspector", "LogisticsPlanner")

CYCLE_CREATE = {
    "production_order_id": {"type": "string", "required": True},
    "oven_station_id": {"type": "string", "required": True},
    "arm_index": {"type": "int", "required": True, "min": 1,
                  "bound_error": "ERR_VALIDATION"},
    "cooling_bay_id": {"type": "string", "required": True},
    "operator_technician_id": {"type": "string", "required": False},
    "oven_start_at": {"type": "ts", "required": True},
    "scheduled_oven_minutes": {"type": "int", "required": True, "min": 1, "max": 600},
    "scheduled_cooling_minutes": {"type": "int", "required": True, "min": 1, "max": 600},
    "oven_temp_c": {"type": "dec", "places": 1, "required": True,
                    "min": "200.0", "max": "360.0"},
    "arm_rpm_major": {"type": "dec", "places": 2, "required": True, "gt": 0},
    "arm_rpm_minor": {"type": "dec", "places": 2, "required": True, "gt": 0},
    "cooling_mode": {"type": "enum", "required": True, "values": rt.AIRFLOW_MODES},
    "expected_production_order_version": {"type": "int", "required": True, "min": 1},
    "exclude_mold_ids": {"type": "array", "required": False},
}


@bp.route("/molding-cycles", methods=["POST"])
def create_cycle():
    ctx = auth.authenticate(("MoldingOperator",))
    body = body_json()
    checks = Checks()
    holder = {}
    add_schema(checks, body, CYCLE_CREATE)

    def resolve():
        holder["order"] = rt.find("production_orders", body.get("production_order_id"))
        holder["station"] = rt.find("oven_stations", body.get("oven_station_id"))
        holder["bay"] = rt.find("cooling_bays", body.get("cooling_bay_id"))
        holder["model"] = S.product_models.get(holder["order"]["product_model_id"])

    def acting_identity():
        supplied = body.get("operator_technician_id")
        if supplied is None:
            return
        rt.find("technicians", supplied)
        if supplied != ctx.user_id:
            fail("ERR_ROLE_IDENTITY_MISMATCH",
                 "operator_technician_id must equal the acting identifier.")

    def exclusion_shape():
        raw = body.get("exclude_mold_ids")
        if raw is None:
            return
        for element in raw:
            if not isinstance(element, str):
                fail("ERR_VALIDATION", "exclude_mold_ids holds a non-string element.")

    def arm_bounds():
        if body["arm_index"] > holder["station"]["arm_count"]:
            fail("ERR_VALIDATION",
                 "arm_index exceeds the station's arm_count of %d."
                 % holder["station"]["arm_count"])

    def station_up():
        if holder["station"]["status"] != "OPERATIONAL":
            fail("ERR_OVEN_STATION_DOWN", "The oven station is DOWN.")

    def bay_up():
        if holder["bay"]["status"] != "OPERATIONAL":
            fail("ERR_COOLING_BAY_DOWN", "The cooling bay is DOWN.")

    def order_schedulable():
        if holder["order"]["status"] not in ("READY_TO_SCHEDULE", "IN_PRODUCTION"):
            fail("ERR_ORDER_NOT_SCHEDULABLE",
                 "Order status is %s." % holder["order"]["status"])

    def mode_matches():
        if body["cooling_mode"] != holder["bay"]["airflow_mode"]:
            fail("ERR_COOLING_MODE_MISMATCH",
                 "cooling_mode must equal the bay's airflow_mode.")

    def size_class_supported():
        model, station = holder["model"], holder["station"]
        if calc.SIZE_RANK[model["size_class"]] > \
                calc.SIZE_RANK[station["max_size_class"]]:
            fail("ERR_SIZE_CLASS_NOT_SUPPORTED",
                 "The hull's size class exceeds the station's max_size_class.")

    def not_back_dated():
        if holder["start"] < core.now():
            fail("ERR_OVEN_START_IN_PAST", "oven_start_at precedes the logical clock.")

    def project():
        values = coerce(body, CYCLE_CREATE)
        holder["start"] = values["oven_start_at"]
        holder["windows"] = calc.project_windows(
            values["oven_start_at"], values["scheduled_oven_minutes"],
            values["scheduled_cooling_minutes"])

    def arm_window():
        oven_end = holder["windows"][0]
        if calc.oven_arm_conflicts(holder["station"], body["arm_index"],
                                   holder["start"], oven_end):
            fail("ERR_OVEN_WINDOW_CONFLICT",
                 "The arm is already booked over that oven window.")

    def bay_slots():
        _oven_end, cool_start, cool_end = holder["windows"]
        hits = calc.cooling_bay_intersecting(holder["bay"], cool_start, cool_end)
        if len(hits) >= holder["bay"]["concurrent_slot_capacity"]:
            fail("ERR_COOLING_BAY_CAPACITY_EXCEEDED",
                 "The bay has no free slot over that cooling window.")

    def pick_mold():
        _oven_end, _cool_start, cool_end = holder["windows"]
        mold, error_id = calc.select_mold(
            holder["order"], holder["station"], holder["start"], cool_end,
            body.get("exclude_mold_ids"))
        if mold is None:
            fail(error_id, "No tool can be booked for that window.")
        holder["mold"] = mold

    def overbuild():
        order = holder["order"]
        ceiling = calc.overbuild_ceiling(order)
        scheduled = 0
        for cycle in calc.cycles_of_order(order):
            if cycle["status"] in ("SCHEDULED", "OVEN_RUNNING", "COOLING"):
                mold = S.molds.get(cycle.get("mold_id"))
                scheduled += mold["cavity_count"] if mold else 0
        produced = len(calc.units_of_order(order))
        if produced + scheduled + holder["mold"]["cavity_count"] > ceiling:
            fail("ERR_ORDER_OVERBUILD",
                 "The order would exceed its overbuild ceiling of %d." % ceiling)

    def occ():
        if body["expected_production_order_version"] != holder["order"]["version"]:
            fail("ERR_STALE_PRODUCTION_ORDER_VERSION",
                 "expected_production_order_version does not match.")

    checks.add(12, resolve)
    checks.add(12.5, acting_identity)
    checks.add(20.5, exclusion_shape)
    checks.add(22.5, arm_bounds)
    checks.add(23.9, project)
    checks.add(30, lambda: auth.require_active(ctx.technician))
    checks.add(32, station_up)
    checks.add(33, bay_up)
    checks.add(34, order_schedulable)
    checks.add(58, mode_matches)
    checks.add(59, size_class_supported)
    checks.add(61.5, not_back_dated)
    checks.add(62, arm_window)
    checks.add(62.5, bay_slots)
    checks.add(70, pick_mold)
    checks.add(79, overbuild)
    checks.add(80, occ)
    checks.run()

    values = coerce(body, CYCLE_CREATE)
    oven_end, cool_start, cool_end = holder["windows"]
    order, mold = holder["order"], holder["mold"]
    row = {
        "production_order_id": order["id"],
        "oven_station_id": holder["station"]["id"],
        "arm_index": values["arm_index"],
        "cooling_bay_id": holder["bay"]["id"],
        "operator_technician_id": ctx.user_id,
        "mold_id": mold["id"],
        "oven_start_at": values["oven_start_at"],
        "scheduled_oven_minutes": values["scheduled_oven_minutes"],
        "scheduled_cooling_minutes": values["scheduled_cooling_minutes"],
        "oven_temp_c": values["oven_temp_c"],
        "arm_rpm_major": values["arm_rpm_major"],
        "arm_rpm_minor": values["arm_rpm_minor"],
        "cooling_mode": values["cooling_mode"],
        "oven_end_at": oven_end,
        "cooling_window_start_at": cool_start,
        "cooling_window_end_at": cool_end,
        "actual_oven_start_at": None,
        "actual_oven_end_at": None,
        "actual_cooling_end_at": None,
        "actual_oven_minutes": 0,
        "actual_cooling_minutes": 0,
        "charged_mass_kg": q3(ZERO),
        "weighted_melt_index_g10min": None,
        "cycle_regrind_pct": q2(ZERO),
        "provisional_warpage_index": None,
        "status": "SCHEDULED",
        "abort_reason": None,
    }
    core.insert("molding_cycles", row)
    if order["status"] == "READY_TO_SCHEDULE":
        order["status"] = "IN_PRODUCTION"
    touch(order)
    return rt.one("molding_cycles", row, 201)


@bp.route("/molding-cycles", methods=["GET"])
def list_cycles():
    auth.authenticate(CYCLE_READ)
    checks = Checks()
    items = [None]

    def collect():
        rows = core.rows("molding_cycles")
        rows = rt.filter_eq(rows, "production_order_id",
                            str_filter("production_order_id"))
        rows = rt.filter_eq(rows, "mold_id", str_filter("mold_id"))
        rows = rt.filter_eq(rows, "oven_station_id", str_filter("oven_station_id"))
        rows = rt.filter_eq(rows, "cooling_bay_id", str_filter("cooling_bay_id"))
        rows = rt.filter_eq(rows, "operator_technician_id",
                            str_filter("operator_technician_id"))
        rows = rt.filter_eq(rows, "status", enum_filter("status", rt.CYCLE_STATUSES))
        rows = rt.filter_eq(rows, "abort_reason",
                            enum_filter("abort_reason", rt.ABORT_REASONS))
        start_from = ts_filter("oven_start_from")
        if start_from is not None:
            rows = [r for r in rows if r["oven_start_at"] >= start_from]
        start_to = ts_filter("oven_start_to")
        if start_to is not None:
            rows = [r for r in rows if r["oven_start_at"] <= start_to]
        items[0] = rows

    checks.add(21, collect)
    checks.run()
    return rt.many("molding_cycles", items[0])


@bp.route("/molding-cycles/<molding_cycle_id>", methods=["GET"])
def read_cycle(molding_cycle_id):
    auth.authenticate(CYCLE_READ)
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(
        row=rt.find("molding_cycles", molding_cycle_id)))
    checks.run()
    return rt.one("molding_cycles", holder["row"])


# --------------------------------------------------------------------------
# Cycle transitions.  Every manual edge is driven by the cycle's own operator.
# --------------------------------------------------------------------------
START_SPEC = {"actual_oven_start_at": {"type": "ts", "required": True}}
COOL_SPEC = {"actual_oven_end_at": {"type": "ts", "required": True}}
DEMOLD_SPEC = {"actual_cooling_end_at": {"type": "ts", "required": True}}
ABORT_SPEC = {"abort_reason": {"type": "string", "required": True,
                               "min_len": 1, "max_len": 500}}


def recost(order):
    """Recompute the order's cost roll-up without advancing its `version`.

    PRD.md section 3.3 has the roll-up "recomputed at oven start (when charges
    become consumed), at demould, and on every inspection that changes
    `completed_qty`", but section 3.5 enumerates the rows whose revision moves on
    the cycle edges exhaustively: at oven start and at demould "The cycle's and
    the tool's `version` each advance by 1", and on an abort "the cycle's
    `version` advances by 1".  The order is not among them on any of the three,
    so the roll-up alone never advances it — only the status edges of section 3.3
    and the inspection paths of section 3.6 do.
    """
    svc.apply_cost(order)


def _cycle_action(molding_cycle_id, spec, allowed_states, roles=("MoldingOperator",)):
    ctx = auth.authenticate(roles)
    body = body_json()
    checks = Checks()
    holder = {}

    def owner():
        cycle = S.molding_cycles.get(molding_cycle_id)
        if cycle is None or ctx.role != "MoldingOperator":
            return
        if cycle["operator_technician_id"] != ctx.user_id:
            fail("ERR_ROLE_IDENTITY_MISMATCH",
                 "Only the cycle's own operator may drive this edge.")

    def state():
        if holder["row"]["status"] not in allowed_states:
            fail("ERR_CYCLE_INVALID_STATE",
                 "Cycle status is %s." % holder["row"]["status"])

    checks.add(5, owner)
    checks.add(10, lambda: holder.update(
        row=rt.find("molding_cycles", molding_cycle_id)))
    add_schema(checks, body, spec)
    checks.add(30, lambda: auth.require_active(ctx.technician))
    checks.add(35, state)
    return ctx, holder, body, checks


@bp.route("/molding-cycles/<molding_cycle_id>/start-oven", methods=["POST"])
def start_oven(molding_cycle_id):
    ctx, holder, body, checks = _cycle_action(
        molding_cycle_id, START_SPEC, ("SCHEDULED",))

    def mold_available():
        mold = S.molds.get(holder["row"].get("mold_id"))
        holder["mold"] = mold
        if mold is None or mold["status"] != "AVAILABLE":
            fail("ERR_MOLD_NOT_AVAILABLE", "The selected tool is not AVAILABLE.")

    def station_up():
        station = S.oven_stations.get(holder["row"]["oven_station_id"])
        if station["status"] != "OPERATIONAL":
            fail("ERR_OVEN_STATION_DOWN", "The oven station is DOWN.")

    def has_charge():
        reserved = [c for c in calc.charges_of_cycle(holder["row"])
                    if c["status"] == "RESERVED"]
        holder["reserved"] = reserved
        if not reserved:
            fail("ERR_RESIN_INSUFFICIENT", "The cycle holds no reserved charge.")

    def lots_available():
        for charge in holder["reserved"]:
            lot = S.resin_lots.get(charge["resin_lot_id"])
            if lot is None or lot["status"] != "AVAILABLE":
                fail("ERR_RESIN_LOT_NOT_AVAILABLE",
                     "A charged lot is no longer AVAILABLE.")

    def mass_tolerance():
        cycle, mold = holder["row"], holder["mold"]
        model = calc.model_of_cycle(cycle)
        nominal = mold["nominal_charge_kg"]
        deviation = q2(abs(cycle["charged_mass_kg"] - nominal) / nominal
                       * Decimal(100))
        if deviation > model["charge_tolerance_pct"]:
            fail("ERR_CHARGE_MASS_OUT_OF_TOLERANCE",
                 "Charge mass deviates by %s percent." % deviation)

    def regrind_ceiling():
        cycle = holder["row"]
        model = calc.model_of_cycle(cycle)
        if cycle["cycle_regrind_pct"] > model["max_regrind_pct"]:
            fail("ERR_REGRIND_LIMIT_EXCEEDED",
                 "Blended regrind share exceeds the model ceiling.")

    def melt_band():
        cycle = holder["row"]
        model = calc.model_of_cycle(cycle)
        weighted = cycle["weighted_melt_index_g10min"]
        if weighted is None or not calc.melt_index_in_band(model, weighted):
            fail("ERR_MELT_INDEX_OUT_OF_RANGE",
                 "The blended melt index lies outside the model's band.")

    checks.add(35.1, mold_available)
    checks.add(35.2, station_up)
    checks.add(35.3, has_charge)
    checks.add(35.4, lots_available)
    checks.add(35.5, mass_tolerance)
    checks.add(35.6, regrind_ceiling)
    checks.add(35.7, melt_band)
    checks.run()

    cycle, mold = holder["row"], holder["mold"]
    cycle["status"] = "OVEN_RUNNING"
    cycle["actual_oven_start_at"] = core.now()
    for charge in core.sorted_rows(holder["reserved"]):
        lot = S.resin_lots.get(charge["resin_lot_id"])
        charge["status"] = "CONSUMED"
        touch(charge)
        svc.lot_consume(lot, charge["charge_kg"])
    svc.recompute_cycle_rollups(cycle)
    touch(cycle)
    mold["status"] = "IN_CYCLE"
    touch(mold)
    order = S.production_orders.get(cycle["production_order_id"])
    if order["status"] == "READY_TO_SCHEDULE":
        order["status"] = "IN_PRODUCTION"
        touch(order)
    recost(order)
    return rt.one("molding_cycles", cycle)


@bp.route("/molding-cycles/<molding_cycle_id>/enter-cooling", methods=["POST"])
def enter_cooling(molding_cycle_id):
    ctx, holder, body, checks = _cycle_action(
        molding_cycle_id, COOL_SPEC, ("OVEN_RUNNING",))

    def bay_up():
        bay = S.cooling_bays.get(holder["row"]["cooling_bay_id"])
        holder["bay"] = bay
        if bay["status"] != "OPERATIONAL":
            fail("ERR_COOLING_BAY_DOWN", "The cooling bay is DOWN.")

    def slot_free():
        bay = holder["bay"]
        occupied = sum(1 for c in core.rows("molding_cycles")
                       if c["cooling_bay_id"] == bay["id"] and c["status"] == "COOLING")
        if occupied >= bay["concurrent_slot_capacity"]:
            fail("ERR_COOLING_BAY_CAPACITY_EXCEEDED",
                 "Every slot in the bay is occupied.")

    checks.add(35.1, bay_up)
    checks.add(35.2, slot_free)
    checks.run()
    cycle = holder["row"]
    cycle["status"] = "COOLING"
    cycle["actual_oven_end_at"] = core.now()
    cycle["actual_oven_minutes"] = floor_int(
        Decimal((cycle["actual_oven_end_at"]
                 - cycle["actual_oven_start_at"]).total_seconds()) / Decimal(60))
    touch(cycle)
    return rt.one("molding_cycles", cycle)


@bp.route("/molding-cycles/<molding_cycle_id>/demold", methods=["POST"])
def demold(molding_cycle_id):
    ctx, holder, body, checks = _cycle_action(
        molding_cycle_id, DEMOLD_SPEC, ("COOLING",))

    def cooling_floor():
        cycle = holder["row"]
        model = calc.model_of_cycle(cycle)
        elapsed = floor_int(
            Decimal((core.now() - cycle["actual_oven_end_at"]).total_seconds())
            / Decimal(60))
        holder["elapsed"] = elapsed
        if elapsed < model["min_cooling_minutes"]:
            fail("ERR_COOLING_TIME_INSUFFICIENT",
                 "Only %d cooling minutes elapsed." % elapsed)

    checks.add(54, cooling_floor)
    checks.run()
    cycle = holder["row"]
    model = calc.model_of_cycle(cycle)
    mold = S.molds.get(cycle["mold_id"])
    order = S.production_orders.get(cycle["production_order_id"])
    cycle["status"] = "DEMOLDED"
    cycle["actual_cooling_end_at"] = core.now()
    cycle["actual_cooling_minutes"] = holder["elapsed"]
    cycle["provisional_warpage_index"] = calc.warpage_index(
        model, cycle, "PROVISIONAL")
    touch(cycle)
    mold["status"] = "AVAILABLE"
    mold["cycles_since_service"] = mold["cycles_since_service"] + 1
    touch(mold)
    svc.mint_units(cycle, mold, order)
    # CASCADE-B link 1: a tool that reached its service interval goes down.
    if mold["cycles_since_service"] >= mold["service_interval_cycles"]:
        mold["status"] = "MAINTENANCE"
        touch(mold)
        # Links 2-4: other SCHEDULED cycles on the tool abort and give back mass.
        svc.abort_scheduled_cycles(
            lambda c: c.get("mold_id") == mold["id"] and c["id"] != cycle["id"],
            "MOLD_SERVICE_DUE", "MOLD_SERVICE_DUE")
        # Link 5: resin-blocked orders the revived lots qualify for are unblocked.
        svc.sweep_unblock_resin()
    recost(order)
    return rt.one("molding_cycles", cycle)


@bp.route("/molding-cycles/<molding_cycle_id>/abort", methods=["POST"])
def abort_cycle_route(molding_cycle_id):
    ctx, holder, body, checks = _cycle_action(
        molding_cycle_id, ABORT_SPEC, ("SCHEDULED", "OVEN_RUNNING", "COOLING"),
        roles=("MoldingOperator", "PlantAdmin"))
    checks.run()
    cycle = holder["row"]
    order = S.production_orders.get(cycle["production_order_id"])
    # CASCADE-A: charges reserved on a SCHEDULED cycle come back; charges already
    # CONSUMED past oven start never do, so no lot is revived from those.
    released = svc.abort_cycle(cycle, "OPERATOR_ABORT", "CYCLE_ABORTED")
    cycle["abort_reason"] = "OPERATOR_ABORT"
    if released:
        svc.sweep_unblock_resin()
    recost(order)
    return rt.one("molding_cycles", cycle)
