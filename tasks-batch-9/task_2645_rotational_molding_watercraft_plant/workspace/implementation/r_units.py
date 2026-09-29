"""FinishedUnit routes.

A hull carries two independent state axes on one row.  `build_status` is driven
by the shop floor (trim, outfit, inspect, scrap) and `logistics_status` by the
warehouse and trailer workflows (store, release-storage, and the trailer edges
in r_ship.py).  Every shop-floor edge carries a cross-axis guard that refuses a
hull which has left UNALLOCATED, and the storage edge carries the reverse guard.

CASCADE-C (release-storage, with anchor promotion), CASCADE-D (an adverse
re-inspection demoting a SELLABLE hull and re-opening its order) and CASCADE-H
(store, with the site footprint/posture recompute) all live here.
"""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import core
import rt
import svc
from core import Checks, S, ZERO, q2, q3, q4, touch
from errors import fail
from schema import (add_schema, body_json, bool_filter, coerce, enum_filter,
                    str_filter)

bp = Blueprint("units", __name__)

UNIT_READ = ("PlantAdmin", "AssemblyTechnician", "QualityInspector",
             "LogisticsPlanner", "WarrantyAgent")
UNIT_READ_ONE = UNIT_READ + ("Customer",)


def _cycle_of(unit):
    return S.molding_cycles.get(unit["molding_cycle_id"])


def _order_of(unit):
    cycle = _cycle_of(unit)
    if cycle is None:
        return None
    return S.production_orders.get(cycle["production_order_id"])


def _model_of(unit):
    return S.product_models.get(unit["product_model_id"])


def _settle_order(order):
    """Recompute the order's completion counters, its COMPLETE / IN_PRODUCTION
    edge and its cost roll-up, then bump it.  The declared side effect of both
    inspect and scrap is an unconditional ProductionOrder version increment."""
    if order is None:
        return
    svc.recompute_completion(order)
    touch(order)


@bp.route("/finished-units", methods=["GET"])
def list_units():
    auth.authenticate(UNIT_READ)
    checks = Checks()
    items = [None]

    def collect():
        rows = core.rows("finished_units")
        rows = rt.filter_eq(rows, "molding_cycle_id", str_filter("molding_cycle_id"))
        rows = rt.filter_eq(rows, "product_model_id", str_filter("product_model_id"))
        rows = rt.filter_eq(rows, "warehouse_id", str_filter("warehouse_id"))
        rows = rt.filter_eq(rows, "outfitted_by_technician_id",
                            str_filter("outfitted_by_technician_id"))
        rows = rt.filter_eq(rows, "inspected_by_technician_id",
                            str_filter("inspected_by_technician_id"))
        rows = rt.filter_eq(rows, "demand_bucket_id", str_filter("demand_bucket_id"))
        rows = rt.filter_eq(rows, "build_status",
                            enum_filter("build_status", rt.BUILD_STATUSES))
        rows = rt.filter_eq(rows, "logistics_status",
                            enum_filter("logistics_status", rt.LOGISTICS_STATUSES))
        rows = rt.filter_eq(rows, "inspection_verdict",
                            enum_filter("inspection_verdict", rt.VERDICTS))
        rows = rt.filter_eq(rows, "storage_zone_code", str_filter("storage_zone_code"))
        rows = rt.filter_eq(rows, "is_zone_anchor", bool_filter("is_zone_anchor"))
        items[0] = rows

    checks.add(21, collect)
    checks.run()
    return rt.many("finished_units", items[0])


@bp.route("/finished-units/<finished_unit_id>", methods=["GET"])
def read_unit(finished_unit_id):
    ctx = auth.authenticate(UNIT_READ_ONE)
    checks = Checks()
    holder = {}
    checks.add(6, lambda: auth.scope_unit(ctx, S.finished_units.get(finished_unit_id)))
    checks.add(10, lambda: holder.update(
        row=rt.find("finished_units", finished_unit_id)))
    checks.run()
    return rt.one("finished_units", holder["row"])


# --------------------------------------------------------------------------
# Shop-floor axis: trim, outfit, inspect, scrap.
#
# Ladder rungs shared by all four: 30 (suspended), 31 (certification),
# 38 (build_status), 39 (logistics_status, the parallel-axis guard) and
# 57 (segregation of duties).
# --------------------------------------------------------------------------
TRIM_SPEC = {"trim_waste_kg": {"type": "dec", "places": 3, "required": True,
                               "min": 0}}
OUTFIT_SPEC = {"hardware_kit_serial": {"type": "string", "required": True,
                                       "min_len": 3, "max_len": 32}}
INSPECT_SPEC = {
    "wall_thickness_points": {"type": "array", "required": True},
    "impact_test_joules": {"type": "dec", "places": 2, "required": True, "min": 0},
    "cosmetic_defect_grade": {"type": "enum", "required": True,
                              "values": rt.COSMETIC_GRADES},
}
SCRAP_SPEC = {"scrap_reason": {"type": "string", "required": True,
                              "min_len": 1, "max_len": 500}}


def _floor_action(finished_unit_id, spec, roles, allowed_build):
    """Shared prologue for every build-axis edge."""
    ctx = auth.authenticate(roles)
    body = body_json()
    checks = Checks()
    holder = {}

    def build_state():
        if holder["row"]["build_status"] not in allowed_build:
            fail("ERR_UNIT_INVALID_BUILD_STATE",
                 "Hull build_status is %s." % holder["row"]["build_status"])

    def unallocated():
        if holder["row"]["logistics_status"] != "UNALLOCATED":
            fail("ERR_UNIT_NOT_REINSPECTABLE",
                 "A hull in logistics_status %s can no longer be worked."
                 % holder["row"]["logistics_status"])

    checks.add(10, lambda: holder.update(
        row=rt.find("finished_units", finished_unit_id)))
    add_schema(checks, body, spec)
    checks.add(30, lambda: auth.require_active(ctx.technician))
    checks.add(38, build_state)
    checks.add(39, unallocated)
    return ctx, holder, body, checks


@bp.route("/finished-units/<finished_unit_id>/trim", methods=["POST"])
def trim_unit(finished_unit_id):
    ctx, holder, body, checks = _floor_action(
        finished_unit_id, TRIM_SPEC, ("AssemblyTechnician",),
        ("DEMOLDED", "REWORK"))
    checks.run()
    unit = holder["row"]
    values = coerce(body, TRIM_SPEC)
    unit["trim_waste_kg"] = values["trim_waste_kg"]
    if unit["build_status"] == "REWORK":
        # The rework loop edge: outfitting must be redone from scratch.
        unit["hardware_kit_serial"] = None
    unit["build_status"] = "TRIMMED"
    touch(unit)
    return rt.one("finished_units", unit)


@bp.route("/finished-units/<finished_unit_id>/outfit", methods=["POST"])
def outfit_unit(finished_unit_id):
    ctx, holder, body, checks = _floor_action(
        finished_unit_id, OUTFIT_SPEC, ("AssemblyTechnician",), ("TRIMMED",))

    def segregation():
        if holder["row"]["inspected_by_technician_id"] == ctx.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "A technician who inspected this hull may not outfit it.")

    checks.add(31, lambda: auth.require_cert(ctx.technician, ("FIXTURE_ASSEMBLY",)))
    checks.add(57, segregation)
    checks.run()
    unit = holder["row"]
    unit["hardware_kit_serial"] = body["hardware_kit_serial"]
    unit["outfitted_by_technician_id"] = ctx.user_id
    unit["build_status"] = "OUTFITTED"
    touch(unit)
    return rt.one("finished_units", unit)


def _numeric(value):
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, Decimal, float))


@bp.route("/finished-units/<finished_unit_id>/inspect", methods=["POST"])
def inspect_unit(finished_unit_id):
    ctx, holder, body, checks = _floor_action(
        finished_unit_id, INSPECT_SPEC, ("QualityInspector",),
        ("OUTFITTED", "SELLABLE"))

    def measurements():
        raw = body.get("wall_thickness_points")
        if not isinstance(raw, list) or len(raw) < 6:
            fail("ERR_INSUFFICIENT_MEASUREMENTS",
                 "At least six wall-thickness measurements are required.")
        points = []
        for element in raw:
            if not _numeric(element):
                fail("ERR_INSUFFICIENT_MEASUREMENTS",
                     "Every wall-thickness measurement must be numeric.")
            point = element if isinstance(element, Decimal) else Decimal(str(element))
            if not point.is_finite() or point <= ZERO:
                fail("ERR_INSUFFICIENT_MEASUREMENTS",
                     "Every wall-thickness measurement must exceed 0.000.")
            points.append(point)
        holder["points"] = points

    def segregation():
        unit = holder["row"]
        cycle = _cycle_of(unit)
        if cycle is not None and cycle["operator_technician_id"] == ctx.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The producing cycle's operator may not inspect this hull.")
        if unit["outfitted_by_technician_id"] == ctx.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The technician who outfitted this hull may not inspect it.")

    checks.add(25, measurements)
    checks.add(31, lambda: auth.require_cert(ctx.technician,
                                             ("WALL_GAUGE", "IMPACT_RIG")))
    checks.add(57, segregation)
    checks.run()

    unit = holder["row"]
    values = coerce(body, INSPECT_SPEC)
    model = _model_of(unit)
    cycle = _cycle_of(unit)
    order = _order_of(unit)
    # A re-inspection replaces the previous array wholesale, in the order given.
    points = holder["points"]
    mean, sd, cv, minimum = calc.wall_distribution(points)
    unit["wall_thickness_points"] = points
    unit["mean_wall_thickness_mm"] = mean
    unit["wall_sd_mm"] = sd
    unit["wall_cv_pct"] = cv
    unit["min_wall_thickness_mm"] = minimum
    unit["impact_test_joules"] = values["impact_test_joules"]
    unit["cosmetic_defect_grade"] = values["cosmetic_defect_grade"]
    # The FINAL variant takes the live wall_cv_pct and the ACTUAL cooling minutes.
    unit["final_warpage_index"] = calc.warpage_index(model, cycle, "FINAL", cv)
    verdict = calc.inspection_verdict(model, unit)
    unit["inspection_verdict"] = verdict
    unit["inspected_by_technician_id"] = ctx.user_id
    if verdict == "PASS":
        unit["build_status"] = "SELLABLE"
    elif verdict == "REWORK":
        # CASCADE-D link 1 on a re-inspection: SELLABLE -> REWORK.
        unit["build_status"] = "REWORK"
        unit["rework_count"] = unit["rework_count"] + 1
        unit["hardware_kit_serial"] = None
    else:
        unit["build_status"] = "SCRAPPED"
    touch(unit)
    # CASCADE-D links 2-3: the order's completed_qty is recomputed (downward when
    # a SELLABLE hull was demoted), its cost roll-up and unit_cost_cents follow,
    # and a COMPLETE order falling short of ordered_qty re-opens as IN_PRODUCTION.
    _settle_order(order)
    return rt.one("finished_units", unit)


@bp.route("/finished-units/<finished_unit_id>/scrap", methods=["POST"])
def scrap_unit(finished_unit_id):
    ctx, holder, body, checks = _floor_action(
        finished_unit_id, SCRAP_SPEC, ("QualityInspector",),
        ("OUTFITTED", "SELLABLE", "REWORK"))

    def segregation():
        unit = holder["row"]
        cycle = _cycle_of(unit)
        if cycle is not None and cycle["operator_technician_id"] == ctx.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The producing cycle's operator may not scrap this hull.")
        if unit["outfitted_by_technician_id"] == ctx.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The technician who outfitted this hull may not scrap it.")

    checks.add(57, segregation)
    checks.run()
    unit = holder["row"]
    unit["scrap_reason"] = body["scrap_reason"]
    unit["build_status"] = "SCRAPPED"
    unit["inspection_verdict"] = "SCRAP"
    touch(unit)
    _settle_order(_order_of(unit))
    return rt.one("finished_units", unit)


# --------------------------------------------------------------------------
# Logistics axis: store (CASCADE-H) and release-storage (CASCADE-C).
#
# The destination is never chosen by the caller: it is the producing order's
# target_warehouse_id, and the zone inside it is picked by the server.
# --------------------------------------------------------------------------
STORE_SPEC = {"expected_warehouse_version": {"type": "int", "required": True,
                                             "min": 1}}
RELEASE_STORAGE_SPEC = {"release_reason": {"type": "string", "required": True,
                                           "min_len": 1, "max_len": 500}}


@bp.route("/finished-units/<finished_unit_id>/store", methods=["POST"])
def store_unit(finished_unit_id):
    auth.authenticate(("LogisticsPlanner",))
    body = body_json()
    checks = Checks()
    holder = {}

    def resolve():
        unit = holder["row"]
        order = _order_of(unit)
        if order is None:
            fail("ERR_PRODUCTION_ORDER_NOT_FOUND",
                 "The producing order no longer exists.")
        holder["order"] = order
        holder["site"] = rt.find("warehouses", order["target_warehouse_id"])
        holder["model"] = _model_of(unit)
        holder["bucket"] = (S.demand_buckets.get(order["demand_bucket_id"])
                            if order.get("demand_bucket_id") else None)

    def build_state():
        if holder["row"]["build_status"] != "SELLABLE":
            fail("ERR_UNIT_INVALID_BUILD_STATE",
                 "Only a SELLABLE hull may be stored; this one is %s."
                 % holder["row"]["build_status"])

    def logistics_state():
        if holder["row"]["logistics_status"] != "UNALLOCATED":
            fail("ERR_UNIT_INVALID_LOGISTICS_STATE",
                 "Hull logistics_status is %s." % holder["row"]["logistics_status"])

    def not_frozen():
        if holder["site"]["posture"] == "FROZEN":
            fail("ERR_WAREHOUSE_FROZEN", "The destination site is FROZEN.")

    def in_window():
        bucket = holder["bucket"]
        if bucket is None:
            return
        today = core.clock_date()
        if today < bucket["window_start_on"] or today > bucket["window_end_on"]:
            fail("ERR_BUILD_AHEAD_WINDOW_MISMATCH",
                 "The logical-clock date lies outside the bucket window.")

    def zone_exists():
        zone = calc.select_zone(holder["site"], holder["model"])
        if zone is None:
            fail("ERR_NO_ELIGIBLE_ZONE",
                 "No zone at the site can take the hull's nested footprint.")
        holder["zone"] = zone

    def quota():
        bucket = holder["bucket"]
        if bucket is None:
            return
        committed = calc.build_ahead_committed_qty(bucket)
        if committed + 1 > calc.build_ahead_cap_qty(bucket):
            fail("ERR_BUILD_AHEAD_CAP_EXCEEDED",
                 "The bucket's build-ahead cap is already reached.")

    def site_cube():
        site = holder["site"]
        total = q4(calc.warehouse_committed_cube(site) + holder["zone"]["footprint"])
        if total > site["footprint_capacity_cube_m3"]:
            fail("ERR_WAREHOUSE_CUBE_EXCEEDED",
                 "The site's total committed cube would exceed its capacity.")

    def occ():
        if body["expected_warehouse_version"] != holder["site"]["version"]:
            fail("ERR_STALE_WAREHOUSE_VERSION",
                 "expected_warehouse_version does not match the stored version.")

    checks.add(10, lambda: holder.update(
        row=rt.find("finished_units", finished_unit_id)))
    checks.add(11, resolve)
    add_schema(checks, body, STORE_SPEC)
    checks.add(38, build_state)
    checks.add(38.5, logistics_state)
    checks.add(40, not_frozen)
    checks.add(69, in_window)
    checks.add(73, zone_exists)
    checks.add(74, quota)
    checks.add(75, site_cube)
    checks.add(82, occ)
    checks.run()

    unit, order, site = holder["row"], holder["order"], holder["site"]
    zone = holder["zone"]
    unit["logistics_status"] = "STORED"
    unit["warehouse_id"] = site["id"]
    unit["demand_bucket_id"] = order.get("demand_bucket_id")
    unit["stored_at"] = core.now()
    unit["storage_zone_code"] = zone["zone_code"]
    unit["stored_footprint_cube_m3"] = zone["footprint"]
    # Opening a new nest group charges the full gross cube and anchors the zone;
    # joining an existing group charges the nested cube and stays a follower.
    unit["is_zone_anchor"] = not zone["anchor_exists"]
    touch(unit)
    # CASCADE-H links 2-4: committed cube, utilisation, posture, then the
    # order-blocking sweep for a site that has reached its frozen threshold.
    svc.recompute_warehouse(site)
    svc.recompute_bucket_of(unit["demand_bucket_id"])
    return rt.one("finished_units", unit)


@bp.route("/finished-units/<finished_unit_id>/release-storage", methods=["POST"])
def release_storage(finished_unit_id):
    auth.authenticate(("LogisticsPlanner",))
    body = body_json()
    checks = Checks()
    holder = {}

    def logistics_state():
        if holder["row"]["logistics_status"] != "STORED":
            fail("ERR_UNIT_INVALID_LOGISTICS_STATE",
                 "Hull logistics_status is %s." % holder["row"]["logistics_status"])

    def not_loaded():
        for line in core.rows("shipment_lines"):
            if line["finished_unit_id"] == holder["row"]["id"] \
                    and line["status"] == "LOADED":
                fail("ERR_UNIT_INVALID_LOGISTICS_STATE",
                     "The hull still carries a loaded trailer line.")

    checks.add(10, lambda: holder.update(
        row=rt.find("finished_units", finished_unit_id)))
    add_schema(checks, body, RELEASE_STORAGE_SPEC)
    checks.add(38.5, logistics_state)
    checks.add(38.6, not_loaded)
    checks.run()
    unit = holder["row"]
    unit["release_reason"] = body["release_reason"]
    # CASCADE-C links 1-4: vacate, promote the earliest surviving follower of the
    # nest group to anchor at full gross cube, recompute the site, unblock orders.
    svc.release_footprint(unit, "UNALLOCATED", True)
    return rt.one("finished_units", unit)
