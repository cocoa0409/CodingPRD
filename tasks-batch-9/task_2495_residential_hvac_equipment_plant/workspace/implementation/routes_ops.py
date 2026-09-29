"""Warehousing, the build line, testing, and the warranty feedback loop."""

from flask import Blueprint

import calc
import cascade
import db
import derive
import find
import validate
import web
from errors import ApiError
from routes_design import enum_arg, eq_filter, listing
from web import endpoint

bp = Blueprint("ops", __name__)

WAREHOUSE_ROLES = ("PlantAdmin", "ProductionPlanner", "SupplyPlanner")
CELL_ROLES = ("PlantAdmin", "QualityTechnician", "ProductionPlanner", "ReliabilityEngineer")
BUILD_ROLES = (
    "PlantAdmin",
    "ProductionPlanner",
    "ProductionTechnician",
    "QualityTechnician",
    "ReliabilityEngineer",
    "SupplyPlanner",
)
TEST_READ_ROLES = (
    "PlantAdmin",
    "QualityTechnician",
    "ProductionTechnician",
    "ProductionPlanner",
    "ReliabilityEngineer",
)
CLAIM_ROLES = ("PlantAdmin", "WarrantyAnalyst", "ReliabilityEngineer", "DesignEngineer")
CAPA_ROLES = ("PlantAdmin", "ReliabilityEngineer", "SupplyPlanner", "WarrantyAnalyst")


# ------------------------------------------------------------- warehouses
@bp.route("/plant/warehouses", methods=["POST"])
@endpoint(["PlantAdmin"], 201)
def create_warehouse():
    payload = web.body()
    name = validate.str_field(payload, "name")
    capacity = validate.int_field(payload, "pallet_capacity", minimum=1)
    row = db.db.insert("warehouses", {"name": name, "pallet_capacity": capacity})
    return derive.serialize_warehouse(row)


@bp.route("/plant/warehouses", methods=["GET"])
@endpoint(WAREHOUSE_ROLES, 200)
def list_warehouses():
    return listing(db.db.rows("warehouses"), derive.serialize_warehouse)


@bp.route("/plant/warehouses/<row_id>", methods=["GET"])
@endpoint(WAREHOUSE_ROLES, 200)
def read_warehouse(row_id):
    return derive.serialize_warehouse(find.warehouse(row_id))


@bp.route("/plant/warehouses/<row_id>/reservations", methods=["GET"])
@endpoint(WAREHOUSE_ROLES, 200)
def list_warehouse_reservations(row_id):
    warehouse = find.warehouse(row_id)
    rows = derive.warehouse_reservations(warehouse)
    rows = eq_filter(rows, "status", web.filter_value("status"))
    rows = eq_filter(rows, "build_order_id", web.filter_value("build_order_id"))
    return listing(rows, derive.serialize_reservation)


@bp.route("/plant/warehouses/<row_id>/occupancy", methods=["GET"])
@endpoint(WAREHOUSE_ROLES, 200)
def warehouse_occupancy(row_id):
    warehouse = find.warehouse(row_id)
    on_date_arg = web.filter_value("on_date")
    window_start_arg = web.filter_value("window_start")
    window_end_arg = web.filter_value("window_end")

    if on_date_arg is not None:
        subject = validate.parse_date_arg(on_date_arg, "on_date")
    elif window_start_arg is not None:
        subject = validate.parse_date_arg(window_start_arg, "window_start")
    else:
        subject = db.db.today()

    days = [subject]
    if window_start_arg is not None and window_end_arg is not None:
        start = validate.parse_date_arg(window_start_arg, "window_start")
        end = validate.parse_date_arg(window_end_arg, "window_end")
        window_days = derive.day_range(start, end)
        if window_days:
            days = [validate.parse_date_arg(d, "window_start") for d in window_days]

    occupancy_units = derive.occupancy(warehouse, subject.isoformat())
    peak = max([derive.occupancy(warehouse, d.isoformat()) for d in days] or [0])
    return {
        "warehouse_id": warehouse["id"],
        "pallet_capacity": warehouse["pallet_capacity"],
        "on_date": subject.isoformat(),
        "occupancy_units": occupancy_units,
        "peak_occupancy_units": peak,
    }


@bp.route("/plant/warehouses/<row_id>/carrying-cost", methods=["GET"])
@endpoint(WAREHOUSE_ROLES, 200)
def warehouse_carrying_cost(row_id):
    warehouse = find.warehouse(row_id)
    start_arg = web.filter_value("window_start")
    end_arg = web.filter_value("window_end")
    if start_arg is None:
        validate.bad("window_start is required.")
    if end_arg is None:
        validate.bad("window_end is required.")
    start = validate.parse_date_arg(start_arg, "window_start")
    end = validate.parse_date_arg(end_arg, "window_end")
    basis = enum_arg("basis", ("PER_RESERVATION", "POOLED"), "PER_RESERVATION")

    result = calc.carrying_cost(warehouse, start, end, basis)
    return {
        "warehouse_id": warehouse["id"],
        "basis": basis,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "reservation_count": result["reservation_count"],
        "pallet_week_total": result["pallet_week_total"],
        "carrying_cost_cents": result["carrying_cost_cents"],
    }


# --------------------------------------------------- warehouse reservations
RESERVATION_BLOCKED_BUILD_STATES = (
    "LEAK_PASSED",
    "CHARGED",
    "RUN_PASSED",
    "RELEASED_TO_STOCK",
    "SCRAPPED",
    "CANCELLED",
    "HOLD_REGULATORY",
)


@bp.route("/plant/warehouse-reservations", methods=["POST"])
@endpoint(["ProductionPlanner"], 201)
def create_reservation():
    payload = web.body()
    warehouse_id = validate.str_field(payload, "warehouse_id")
    build_id = validate.str_field(payload, "build_order_id")
    start_raw, start = validate.date_field(payload, "start_date")
    end_raw, end = validate.date_field(payload, "end_date")
    pallet_units = validate.int_field(payload, "pallet_units", minimum=1)
    if end <= start:
        raise ApiError("ERR_INVALID_INTERVAL", "end_date must be after start_date.")

    warehouse = find.warehouse(warehouse_id)
    build = find.build(build_id)

    if not build["is_preseason"] or build["status"] in RESERVATION_BLOCKED_BUILD_STATES:
        raise ApiError(
            "ERR_RESERVATION_NOT_ALLOWED_FOR_BUILD",
            "Only a pre-season lot still in production may hold pallet space.",
        )

    peak = 0
    for day in derive.day_range(start, end):
        total = derive.occupancy(warehouse, day) + pallet_units
        if total > peak:
            peak = total
    if peak > warehouse["pallet_capacity"]:
        raise ApiError(
            "ERR_WAREHOUSE_CAPACITY_EXCEEDED",
            "The reservation would exceed the warehouse pallet capacity.",
        )

    row = db.db.insert(
        "reservations",
        {
            "warehouse_id": warehouse_id,
            "build_order_id": build_id,
            "start_date": start_raw,
            "end_date": end_raw,
            "pallet_units": pallet_units,
            "status": "ACTIVE",
            "released_at": None,
            "release_reason": None,
            "_start_date": start,
            "_end_date": end,
        },
    )
    db.db.touch(warehouse)
    return derive.serialize_reservation(row)


@bp.route("/plant/warehouse-reservations/<row_id>", methods=["GET"])
@endpoint(WAREHOUSE_ROLES, 200)
def read_reservation(row_id):
    return derive.serialize_reservation(find.reservation(row_id))


@bp.route("/plant/warehouse-reservations/<row_id>/release", methods=["POST"])
@endpoint(["ProductionPlanner"], 200)
def release_reservation(row_id):
    payload = web.body()
    reason = validate.str_field(payload, "release_reason", required=False, default=None)
    reservation = find.reservation(row_id)
    if reservation["status"] != "ACTIVE":
        raise ApiError("ERR_RESERVATION_STATE_INVALID", "The reservation is not ACTIVE.")
    cascade.release_reservation(reservation, reason)
    return derive.serialize_reservation(reservation)


# -------------------------------------------------------------- test cells
@bp.route("/plant/test-cells", methods=["POST"])
@endpoint(["PlantAdmin"], 201)
def create_cell():
    payload = web.body()
    cell_code = validate.str_field(payload, "cell_code", max_len=32)
    cooldown = validate.int_field(
        payload, "cooldown_minutes", required=False, minimum=0, maximum=240, default=30
    )
    for existing in db.db.rows("cells"):
        if existing["cell_code"] == cell_code:
            validate.bad("cell_code already exists.")
    row = db.db.insert(
        "cells",
        {"cell_code": cell_code, "cooldown_minutes": cooldown, "status": "ACTIVE"},
    )
    return derive.serialize_cell(row)


@bp.route("/plant/test-cells", methods=["GET"])
@endpoint(CELL_ROLES, 200)
def list_cells():
    rows = eq_filter(db.db.rows("cells"), "status", web.filter_value("status"))
    return listing(rows, derive.serialize_cell)


@bp.route("/plant/test-cells/<row_id>", methods=["GET"])
@endpoint(CELL_ROLES, 200)
def read_cell(row_id):
    return derive.serialize_cell(find.cell(row_id))


@bp.route("/plant/test-cells/<row_id>/run-tests", methods=["GET"])
@endpoint(CELL_ROLES, 200)
def list_cell_run_tests(row_id):
    cell = find.cell(row_id)
    rows = [t for t in db.db.rows("run_tests") if t["test_cell_id"] == cell["id"]]
    rows = eq_filter(rows, "verdict", web.filter_value("verdict"))
    rows = sorted(rows, key=lambda r: (r["_window_start"], r["_seq"]))
    return listing(rows, derive.serialize_run_test)


# ------------------------------------------------------------ build orders
@bp.route("/plant/build-orders", methods=["POST"])
@endpoint(["ProductionPlanner"], 201)
def create_build():
    payload = web.body()
    platform_id = validate.str_field(payload, "platform_id")
    quantity = validate.int_field(payload, "quantity_units", minimum=1)
    start_raw, _ = validate.instant_field(payload, "scheduled_start_utc")
    is_preseason = validate.bool_field(
        payload, "is_preseason", required=False, default=False
    )

    platform = find.platform(platform_id)
    if platform["status"] != "RELEASED":
        raise ApiError(
            "ERR_INVALID_PLATFORM_STATE", "Only a RELEASED platform may take a build lot."
        )
    if derive.warranty_posture(platform) == "DESIGN_CHANGE_REQUIRED":
        raise ApiError(
            "ERR_WARRANTY_POSTURE_BLOCKED",
            "The platform's warranty posture blocks new build lots.",
        )
    program = derive.platform_program(platform)
    if program is not None and db.db.now() >= program["_manufacture_cutoff"]:
        raise ApiError(
            "ERR_MANUFACTURE_WINDOW_CLOSED", "The manufacture window has closed."
        )

    row = db.db.insert(
        "builds",
        {
            "platform_id": platform_id,
            "quantity_units": quantity,
            "is_preseason": is_preseason,
            "scheduled_start_utc": start_raw,
            "status": "DRAFT",
            "rework_count": 0,
            "charge_grams": 0,
            "hold_reason": None,
            "closed_reason": None,
            "released_to_stock_at": None,
        },
    )
    return derive.serialize_build(row)


@bp.route("/plant/build-orders", methods=["GET"])
@endpoint(BUILD_ROLES, 200)
def list_builds():
    rows = db.db.rows("builds")
    rows = eq_filter(rows, "platform_id", web.filter_value("platform_id"))
    rows = eq_filter(rows, "status", web.filter_value("status"))
    preseason = web.filter_bool("is_preseason")
    if preseason is not None:
        rows = [r for r in rows if r["is_preseason"] == preseason]
    return listing(rows, derive.serialize_build)


@bp.route("/plant/build-orders/<row_id>", methods=["GET"])
@endpoint(BUILD_ROLES, 200)
def read_build(row_id):
    return derive.serialize_build(find.build(row_id))


@bp.route("/plant/build-orders/<row_id>/start-coil-fab", methods=["POST"])
@endpoint(["ProductionTechnician"], 200)
def start_coil_fab(row_id):
    web.body()
    build = find.build(row_id)
    if build["status"] not in ("DRAFT", "REWORK"):
        raise ApiError("ERR_BUILD_STAGE_INVALID", "The lot is not in DRAFT or REWORK.")
    platform = find.platform(build["platform_id"])
    if platform["status"] != "RELEASED":
        raise ApiError("ERR_INVALID_PLATFORM_STATE", "The platform is not RELEASED.")
    build["status"] = "COIL_FAB"
    db.db.touch(build)
    return derive.serialize_build(build)


@bp.route("/plant/build-orders/<row_id>/complete-brazing", methods=["POST"])
@endpoint(["ProductionTechnician"], 200)
def complete_brazing(row_id):
    web.body()
    build = find.build(row_id)
    if build["status"] != "COIL_FAB":
        raise ApiError("ERR_BUILD_STAGE_INVALID", "The lot is not in COIL_FAB.")
    build["status"] = "BRAZED"
    db.db.touch(build)
    return derive.serialize_build(build)


@bp.route("/plant/build-orders/<row_id>/charge", methods=["POST"])
@endpoint(["ProductionTechnician"], 200)
def charge_build(row_id):
    payload = web.body()
    charge_grams = validate.int_field(payload, "charge_grams", minimum=0)
    build = find.build(row_id)
    if build["status"] != "LEAK_PASSED":
        raise ApiError("ERR_BUILD_STAGE_INVALID", "The lot has not passed its leak test.")
    platform = find.platform(build["platform_id"])
    program = derive.platform_program(platform)
    if program is not None and db.db.now() >= program["_manufacture_cutoff"]:
        raise ApiError(
            "ERR_MANUFACTURE_WINDOW_CLOSED", "The manufacture window has closed."
        )
    if program is not None and program["flammability_class"] == "A2L":
        limit = platform["max_charge_grams"]
        if limit is None or charge_grams > limit:
            raise ApiError(
                "ERR_FLAMMABLE_CHARGE_LIMIT_EXCEEDED",
                "The charge exceeds the platform's A2L charge ceiling.",
            )
    build["status"] = "CHARGED"
    build["charge_grams"] = charge_grams
    db.db.touch(build)
    return derive.serialize_build(build)


@bp.route("/plant/build-orders/<row_id>/release-to-stock", methods=["POST"])
@endpoint(["ProductionPlanner"], 200)
def release_build_to_stock(row_id):
    web.body()
    build = find.build(row_id)
    if build["status"] != "RUN_PASSED":
        raise ApiError("ERR_BUILD_STAGE_INVALID", "The lot has not passed its run test.")
    platform = find.platform(build["platform_id"])
    if platform["status"] not in ("RELEASED", "RESTRICTED"):
        raise ApiError(
            "ERR_INVALID_PLATFORM_STATE",
            "The platform is neither RELEASED nor RESTRICTED.",
        )
    if build["is_preseason"]:
        today = db.db.today()
        covered = [
            r
            for r in derive.build_reservations(build, ("ACTIVE",))
            if r["_start_date"] <= today < r["_end_date"]
        ]
        if not covered:
            raise ApiError(
                "ERR_NO_WAREHOUSE_RESERVATION",
                "A pre-season lot needs live pallet space to release.",
            )
    build["status"] = "RELEASED_TO_STOCK"
    build["released_to_stock_at"] = db.db.stamp()
    db.db.touch(build)
    db.db.touch(platform)
    return derive.serialize_build(build)


@bp.route("/plant/build-orders/<row_id>/cancel", methods=["POST"])
@endpoint(["ProductionPlanner"], 200)
def cancel_build(row_id):
    payload = web.body()
    reason = validate.str_field(payload, "reason", required=False, default=None)
    build = find.build(row_id)
    if build["status"] not in ("DRAFT", "HOLD_REGULATORY"):
        raise ApiError(
            "ERR_BUILD_STAGE_INVALID",
            "Only a DRAFT or HOLD_REGULATORY lot may be cancelled.",
        )
    build["status"] = "CANCELLED"
    build["closed_reason"] = reason
    db.db.touch(build)
    cascade.release_build_reservations(build, "BUILD_CANCELLED")
    return derive.serialize_build(build)


@bp.route("/plant/build-orders/<row_id>/leak-tests", methods=["GET"])
@endpoint(TEST_READ_ROLES, 200)
def list_build_leak_tests(row_id):
    build = find.build(row_id)
    rows = derive.build_leak_tests(build)
    rows = eq_filter(rows, "method", web.filter_value("method"))
    rows = eq_filter(rows, "verdict", web.filter_value("verdict"))
    return listing(rows, derive.serialize_leak_test)


@bp.route("/plant/build-orders/<row_id>/run-tests", methods=["GET"])
@endpoint(TEST_READ_ROLES, 200)
def list_build_run_tests(row_id):
    build = find.build(row_id)
    rows = derive.build_run_tests(build)
    rows = eq_filter(rows, "verdict", web.filter_value("verdict"))
    return listing(rows, derive.serialize_run_test)


@bp.route("/plant/build-orders/<row_id>/warehouse-reservations", methods=["GET"])
@endpoint(WAREHOUSE_ROLES, 200)
def list_build_reservations(row_id):
    build = find.build(row_id)
    rows = derive.build_reservations(build)
    rows = eq_filter(rows, "status", web.filter_value("status"))
    return listing(rows, derive.serialize_reservation)


# --------------------------------------------------------------- leak tests
def _apply_test_outcome(build, verdict, is_run_test):
    """The shared repair budget of two reworks across leak and run testing."""
    if verdict == "PASS":
        build["status"] = "RUN_PASSED" if is_run_test else "LEAK_PASSED"
        db.db.touch(build)
        return
    build["rework_count"] = build["rework_count"] + 1
    if build["rework_count"] <= 2:
        build["status"] = "REWORK"
        if is_run_test:
            build["charge_grams"] = 0
        db.db.touch(build)
        return
    build["status"] = "SCRAPPED"
    build["closed_reason"] = "REWORK_LIMIT_EXCEEDED"
    if is_run_test:
        build["charge_grams"] = 0
    db.db.touch(build)
    cascade.release_build_reservations(build, "BUILD_SCRAPPED")


@bp.route("/plant/leak-tests", methods=["POST"])
@endpoint(["QualityTechnician"], 201)
def create_leak_test():
    payload = web.body()
    build_id = validate.str_field(payload, "build_order_id")
    method = validate.enum_field(payload, "method", ("HELIUM_MASS_SPEC", "PRESSURE_DECAY"))
    leak_rate = validate.num_field(
        payload, "measured_leak_rate_g_per_year", required=False, places=2, ge=0
    )
    decay = validate.num_field(payload, "decay_kpa", required=False, places=2, ge=0)
    hold_minutes = validate.int_field(
        payload, "hold_minutes", required=False, minimum=0, default=None
    )

    if method == "HELIUM_MASS_SPEC":
        if leak_rate is None:
            validate.bad("measured_leak_rate_g_per_year is required for HELIUM_MASS_SPEC.")
        if decay is not None or hold_minutes is not None:
            validate.bad("HELIUM_MASS_SPEC forbids decay_kpa and hold_minutes.")
    else:
        if decay is None:
            validate.bad("decay_kpa is required for PRESSURE_DECAY.")
        if hold_minutes is None:
            validate.bad("hold_minutes is required for PRESSURE_DECAY.")
        if leak_rate is not None:
            validate.bad("PRESSURE_DECAY forbids measured_leak_rate_g_per_year.")

    build = find.build(build_id)
    if build["status"] != "BRAZED":
        raise ApiError("ERR_BUILD_STAGE_INVALID", "The lot is not BRAZED.")
    if method == "PRESSURE_DECAY" and hold_minutes < calc.MIN_PRESSURE_DECAY_HOLD_MINUTES:
        raise ApiError(
            "ERR_LEAK_TEST_HOLD_TOO_SHORT",
            "A pressure-decay test must hold for at least 15 minutes.",
        )

    platform = find.platform(build["platform_id"])
    program = derive.platform_program(platform)
    flammability = program["flammability_class"] if program else "A1"
    applied_limit, verdict = calc.leak_test_verdict(
        method, flammability, leak_rate, decay, hold_minutes
    )

    row = db.db.insert(
        "leak_tests",
        {
            "build_order_id": build_id,
            "method": method,
            "measured_leak_rate_g_per_year": leak_rate,
            "decay_kpa": decay,
            "hold_minutes": hold_minutes,
            "applied_limit": applied_limit,
            "verdict": verdict,
            "performed_by_user_id": web.actor(),
            "performed_at": db.db.stamp(),
        },
        versioned=False,
    )
    _apply_test_outcome(build, verdict, is_run_test=False)
    return derive.serialize_leak_test(row)


@bp.route("/plant/leak-tests", methods=["GET"])
@endpoint(TEST_READ_ROLES, 200)
def list_leak_tests():
    rows = db.db.rows("leak_tests")
    rows = eq_filter(rows, "build_order_id", web.filter_value("build_order_id"))
    rows = eq_filter(rows, "method", web.filter_value("method"))
    rows = eq_filter(rows, "verdict", web.filter_value("verdict"))
    return listing(rows, derive.serialize_leak_test)


# ---------------------------------------------------------------- run tests
@bp.route("/plant/run-tests", methods=["POST"])
@endpoint(["QualityTechnician"], 201)
def create_run_test():
    payload = web.body()
    build_id = validate.str_field(payload, "build_order_id")
    cell_id = validate.str_field(payload, "test_cell_id")
    start_raw, window_start = validate.instant_field(payload, "window_start_utc")
    end_raw, window_end = validate.instant_field(payload, "window_end_utc")
    capacity = validate.int_field(payload, "measured_capacity_btuh", minimum=0)
    power = validate.int_field(payload, "measured_power_w", minimum=1)
    ambient = validate.num_field(payload, "measured_ambient_c", places=1)
    if window_end <= window_start:
        raise ApiError(
            "ERR_INVALID_INTERVAL", "window_end_utc must be after window_start_utc."
        )

    build = find.build(build_id)
    cell = find.cell(cell_id)
    if build["status"] != "CHARGED":
        raise ApiError("ERR_BUILD_STAGE_INVALID", "The lot is not CHARGED.")

    passing = derive.latest_passing_leak_test(build)
    if passing is not None and web.actor() == passing["performed_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The leak-test technician may not run the performance test.",
        )
    conflict = calc.conflicting_run_test(cell, window_start, window_end)
    if conflict is not None:
        raise ApiError(
            "ERR_TEST_CELL_WINDOW_CONFLICT",
            "The window conflicts with run test %s on this cell." % conflict["id"],
        )

    platform = find.platform(build["platform_id"])
    program = derive.platform_program(platform)
    flammability = program["flammability_class"] if program else "A1"
    computed = calc.run_test_verdict(platform, flammability, capacity, power, ambient)

    row = db.db.insert(
        "run_tests",
        {
            "build_order_id": build_id,
            "test_cell_id": cell_id,
            "window_start_utc": start_raw,
            "window_end_utc": end_raw,
            "measured_capacity_btuh": capacity,
            "measured_power_w": power,
            "measured_ambient_c": ambient,
            "corrected_capacity_btuh": computed["corrected_capacity_btuh"],
            "capacity_ratio": computed["capacity_ratio"],
            "efficiency_ratio": computed["efficiency_ratio"],
            "applied_capacity_tolerance": computed["applied_capacity_tolerance"],
            "applied_efficiency_tolerance": computed["applied_efficiency_tolerance"],
            "verdict": computed["verdict"],
            "performed_by_user_id": web.actor(),
            "performed_at": db.db.stamp(),
            "_window_start": window_start,
            "_window_end": window_end,
        },
        versioned=False,
    )
    _apply_test_outcome(build, computed["verdict"], is_run_test=True)
    return derive.serialize_run_test(row)


@bp.route("/plant/run-tests", methods=["GET"])
@endpoint(TEST_READ_ROLES, 200)
def list_run_tests():
    rows = db.db.rows("run_tests")
    rows = eq_filter(rows, "build_order_id", web.filter_value("build_order_id"))
    rows = eq_filter(rows, "test_cell_id", web.filter_value("test_cell_id"))
    rows = eq_filter(rows, "verdict", web.filter_value("verdict"))
    return listing(rows, derive.serialize_run_test)


# ---------------------------------------------------------- warranty claims
def _matching_supply(platform, component_type, supplier_lot_code):
    part_field = (
        "compressor_part_number"
        if component_type == "COMPRESSOR"
        else "control_board_part_number"
    )
    part_number = platform[part_field]
    candidates = [
        pool
        for pool in db.db.rows("supplies")
        if pool["component_type"] == component_type
        and pool["supplier_lot_code"] == supplier_lot_code
        and pool["part_number"] == part_number
        and pool["status"] in ("ACTIVE", "EXHAUSTED")
    ]
    return candidates[0] if candidates else None


def _open_capa_for(pool):
    for capa in db.db.rows("capas"):
        if capa["component_supply_id"] == pool["id"] and capa["status"] == "OPEN":
            return capa
    return None


def _claim_cohort(platform_id, component_type, supplier_lot_code, statuses):
    return [
        claim
        for claim in db.db.rows("claims")
        if claim["platform_id"] == platform_id
        and claim["component_type"] == component_type
        and claim["supplier_lot_code"] == supplier_lot_code
        and claim["status"] in statuses
    ]


def _open_corrective_action(claim, platform):
    """Hops 2 to 4 of the warranty cascade."""
    if claim["component_type"] is None or claim["supplier_lot_code"] is None:
        return
    if derive.warranty_posture(platform) not in (
        "CAPA_REQUIRED",
        "DESIGN_CHANGE_REQUIRED",
    ):
        return
    pool = _matching_supply(platform, claim["component_type"], claim["supplier_lot_code"])
    if pool is None or _open_capa_for(pool) is not None:
        return

    rate, _, _ = derive.claim_rate(platform, "BUILT_BASIS")
    derate_pct = calc.derate_pct_for(claim["component_type"], rate)
    if derate_pct is None:
        return

    swept = _claim_cohort(
        platform["id"], claim["component_type"], claim["supplier_lot_code"], ("OPEN",)
    )
    for row in cascade.asc(swept):
        row["status"] = "LINKED_TO_CAPA"
        db.db.touch(row)
    cited = _claim_cohort(
        platform["id"],
        claim["component_type"],
        claim["supplier_lot_code"],
        ("OPEN", "LINKED_TO_CAPA"),
    )

    db.db.insert(
        "capas",
        {
            "component_supply_id": pool["id"],
            "warranty_claim_id": claim["id"],
            "supplier_lot_code": claim["supplier_lot_code"],
            "component_type": claim["component_type"],
            "trigger_claim_rate_pct": rate,
            "derate_pct": derate_pct,
            "cited_claim_count": len(cited),
            "status": "OPEN",
            "resolution": None,
            "effectiveness_note": None,
            "closed_by_user_id": None,
            "closed_at": None,
        },
    )
    pool["status"] = "DERATED"
    pool["derate_pct"] = derate_pct
    db.db.touch(pool)
    cascade.rebalance_supply(pool, "SUPPLY_DERATED")


@bp.route("/plant/warranty-claims", methods=["POST"])
@endpoint(["WarrantyAnalyst"], 201)
def create_claim():
    payload = web.body()
    platform_id = validate.str_field(payload, "platform_id")
    failure_code = validate.enum_field(
        payload,
        "failure_code",
        (
            "COMPRESSOR_FAILURE",
            "CONTROL_BOARD_FAULT",
            "COIL_LEAK",
            "CHARGE_LOSS",
            "FAN_MOTOR",
        ),
    )
    claim_cost = validate.int_field(payload, "claim_cost_cents", minimum=0)
    build_id = validate.str_field(payload, "build_order_id", required=False, default=None)
    component_type = validate.enum_field(
        payload,
        "component_type",
        ("COMPRESSOR", "CONTROL_BOARD"),
        required=False,
        default=None,
    )
    supplier_lot_code = validate.str_field(
        payload, "supplier_lot_code", required=False, default=None
    )
    if (component_type is None) != (supplier_lot_code is None):
        validate.bad("component_type and supplier_lot_code must be supplied together.")

    platform = find.platform(platform_id)
    if build_id is not None:
        find.build(build_id)

    row = db.db.insert(
        "claims",
        {
            "platform_id": platform_id,
            "build_order_id": build_id,
            "failure_code": failure_code,
            "component_type": component_type,
            "supplier_lot_code": supplier_lot_code,
            "claim_cost_cents": claim_cost,
            "filed_by_user_id": web.actor(),
            "filed_at": db.db.stamp(),
            "status": "OPEN",
        },
    )
    db.db.touch(platform)
    _open_corrective_action(row, platform)
    return derive.serialize_claim(row)


@bp.route("/plant/warranty-claims", methods=["GET"])
@endpoint(CLAIM_ROLES, 200)
def list_claims():
    rows = db.db.rows("claims")
    rows = eq_filter(rows, "platform_id", web.filter_value("platform_id"))
    rows = eq_filter(rows, "build_order_id", web.filter_value("build_order_id"))
    rows = eq_filter(rows, "status", web.filter_value("status"))
    rows = eq_filter(rows, "component_type", web.filter_value("component_type"))
    rows = eq_filter(rows, "supplier_lot_code", web.filter_value("supplier_lot_code"))
    rows = eq_filter(rows, "failure_code", web.filter_value("failure_code"))
    return listing(rows, derive.serialize_claim)


@bp.route("/plant/warranty-claims/<row_id>", methods=["GET"])
@endpoint(CLAIM_ROLES, 200)
def read_claim(row_id):
    return derive.serialize_claim(find.claim(row_id))


# ----------------------------------------------- supplier corrective actions
@bp.route("/plant/supplier-corrective-actions", methods=["GET"])
@endpoint(CAPA_ROLES, 200)
def list_capas():
    rows = db.db.rows("capas")
    rows = eq_filter(rows, "component_supply_id", web.filter_value("component_supply_id"))
    rows = eq_filter(rows, "warranty_claim_id", web.filter_value("warranty_claim_id"))
    rows = eq_filter(rows, "status", web.filter_value("status"))
    rows = eq_filter(rows, "component_type", web.filter_value("component_type"))
    return listing(rows, derive.serialize_capa)


@bp.route("/plant/supplier-corrective-actions/<row_id>", methods=["GET"])
@endpoint(CAPA_ROLES, 200)
def read_capa(row_id):
    return derive.serialize_capa(find.capa(row_id))


@bp.route("/plant/supplier-corrective-actions/<row_id>/close", methods=["POST"])
@endpoint(["ReliabilityEngineer"], 200)
def close_capa(row_id):
    payload = web.body()
    resolution = validate.enum_field(payload, "resolution", ("EFFECTIVE", "INEFFECTIVE"))
    note = validate.str_field(payload, "effectiveness_note", required=False, default=None)

    capa = find.capa(row_id)
    if capa["status"] != "OPEN":
        raise ApiError(
            "ERR_CORRECTIVE_ACTION_STATE_INVALID", "The corrective action is not OPEN."
        )
    cited_claim = db.db.get("claims", capa["warranty_claim_id"])
    if cited_claim is not None and web.actor() == cited_claim["filed_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The analyst who filed the cited claim may not close the action.",
        )

    pool = db.db.get("supplies", capa["component_supply_id"])
    capa["status"] = "CLOSED_EFFECTIVE" if resolution == "EFFECTIVE" else "CLOSED_INEFFECTIVE"
    capa["resolution"] = resolution
    capa["effectiveness_note"] = note
    capa["closed_by_user_id"] = web.actor()
    capa["closed_at"] = db.db.stamp()
    db.db.touch(capa)

    if resolution == "EFFECTIVE":
        if pool is not None and _open_capa_for(pool) is None:
            pool["status"] = "ACTIVE"
            pool["derate_pct"] = 0
            db.db.touch(pool)
        if cited_claim is not None:
            cohort = _claim_cohort(
                cited_claim["platform_id"],
                capa["component_type"],
                capa["supplier_lot_code"],
                ("LINKED_TO_CAPA",),
            )
            for row in cascade.asc(cohort):
                row["status"] = "CLOSED"
                db.db.touch(row)
            platform = db.db.get("platforms", cited_claim["platform_id"])
            if platform is not None:
                db.db.touch(platform)
    else:
        if pool is not None:
            pool["status"] = "CLOSED"
            pool["derate_pct"] = 100
            db.db.touch(pool)
            cascade.rebalance_supply(pool, "SUPPLY_CLOSED")

    return derive.serialize_capa(capa)
