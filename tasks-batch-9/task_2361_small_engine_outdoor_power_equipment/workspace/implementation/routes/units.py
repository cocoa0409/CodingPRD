"""Engine assembly: staging, torque monitoring, hot test, release, rework, scrap."""

from collections import OrderedDict

from flask import Blueprint

import calc
import store
import svc
import validation as v
from auth import endpoint, READ_ROLES
from errors import ApiError
from response import list_response, object_response
from store import db, set_fields

bp = Blueprint("units", __name__)

BUILD_STATES = ("STAGED", "ASSEMBLED", "HOT_TESTED", "RELEASED", "CANCELLED")
CONFORMANCE_STATES = ("PENDING", "CONFORMING", "NONCONFORMING", "QUARANTINED")
ACCEPTING_ORDER_STATUSES = ("RELEASED", "IN_PRODUCTION")
RELEASABLE_LOT_STATUSES = ("ACCEPTED", "DEVIATION_ACCEPTED")


def _sync_order(order, extra_status=None):
    """Recompute the order's progress counters, optionally with a status move."""
    units = svc.units_of_order(order["id"])
    staged = len([u for u in units if u["build_state"] in ("STAGED", "ASSEMBLED", "HOT_TESTED")])
    built = len([u for u in units if u["build_state"] == "RELEASED"])
    changes = {"staged_quantity": staged, "built_quantity": built}
    # PRD 2.11: built_quantity always equals allocated_dealer_units plus
    # allocated_mass_retail_units plus unallocated_units.  A newly released unit
    # "joins the order's allocation pool" (PRD 3.7), which is the slack bucket
    # until the planner runs the waterfall again.
    changes["unallocated_units"] = (
        built - order["allocated_dealer_units"] - order["allocated_mass_retail_units"]
    )
    if extra_status is not None:
        changes["status"] = extra_status
    set_fields(order, **changes)


def _unit_platform(unit):
    order = db.build_orders.get(unit["build_order_id"])
    if order is None:
        return None
    model = svc.order_model(order)
    if model is None:
        return None
    return svc.model_platform(model)


# ------------------------------------------------------------------- staging

@bp.route("/engine-units", methods=["POST"])
@endpoint(["QualityEngineer"])
def stage_unit():
    payload = v.body()
    order_id = v.id_field(payload, "build_order_id")
    run_id = v.id_field(payload, "machining_run_id")
    carburetor_lot_id = v.id_field(payload, "carburetor_lot_id")
    ignition_lot_id = v.id_field(payload, "ignition_lot_id")
    serial_number = v.string_field(payload, "serial_number", 1, 30)

    carburetor_lot = svc.get_lot(carburetor_lot_id)
    ignition_lot = svc.get_lot(ignition_lot_id)
    run = svc.get_machining_run(run_id)
    order = svc.get_build_order(order_id)

    svc.require_unique(db.engine_units, "serial_number", serial_number)

    if order["status"] not in ACCEPTING_ORDER_STATUSES:
        raise ApiError(
            "ERR_BUILD_ORDER_NOT_ACCEPTING_UNITS",
            "The build order is not accepting new units.",
        )
    if run["status"] != "CLOSED":
        raise ApiError(
            "ERR_MACHINING_RUN_NOT_CLOSED",
            "Only a CLOSED machining run may supply a critical component.",
        )
    for lot in (carburetor_lot, ignition_lot):
        if lot["status"] not in RELEASABLE_LOT_STATUSES:
            raise ApiError(
                "ERR_COMPONENT_LOT_NOT_RELEASABLE",
                "A consumed component lot is not releasable to the line.",
            )

    model = svc.order_model(order)
    if model is None or run["engine_platform_id"] != model["engine_platform_id"]:
        raise ApiError(
            "ERR_PLATFORM_MISMATCH",
            "The machining run was cut for a different engine platform.",
        )

    if carburetor_lot["component_category"] != "CARBURETOR":
        raise ApiError(
            "ERR_COMPONENT_CATEGORY_MISMATCH",
            "carburetor_lot_id must name a CARBURETOR lot.",
        )
    if ignition_lot["component_category"] != "IGNITION":
        raise ApiError(
            "ERR_COMPONENT_CATEGORY_MISMATCH",
            "ignition_lot_id must name an IGNITION lot.",
        )

    if order["staged_quantity"] + order["built_quantity"] + 1 > order["planned_quantity"]:
        raise ApiError(
            "ERR_BUILD_ORDER_QUANTITY_EXCEEDED",
            "Staging one more unit would exceed the order's planned quantity.",
        )
    for lot in (carburetor_lot, ignition_lot):
        if (lot["remaining_qty"] or 0) < 1:
            raise ApiError(
                "ERR_COMPONENT_LOT_DEPLETED",
                "A consumed component lot has no remaining pieces.",
            )

    deviation_sourced = bool(carburetor_lot["deviation_flag"]) or bool(ignition_lot["deviation_flag"])

    unit = store.new_record(OrderedDict([
        ("build_order_id", order["id"]),
        ("machining_run_id", run["id"]),
        ("carburetor_lot_id", carburetor_lot["id"]),
        ("ignition_lot_id", ignition_lot["id"]),
        ("serial_number", serial_number),
        ("build_state", "STAGED"),
        ("conformance_state", "PENDING"),
        ("torque_readings", None),
        ("out_of_spec_fastener_count", None),
        ("measured_rpm", None),
        ("measured_emission_g_per_kwh", None),
        ("hot_test_emission_threshold", None),
        ("deviation_sourced", deviation_sourced),
        ("rework_count", 0),
        ("released_at", None),
    ]))
    db.engine_units[unit["id"]] = unit

    for lot in (carburetor_lot, ignition_lot):
        set_fields(
            lot,
            consumed_qty=lot["consumed_qty"] + 1,
            remaining_qty=lot["remaining_qty"] - 1,
        )

    _sync_order(order, "IN_PRODUCTION" if order["status"] == "RELEASED" else None)
    return object_response(store.public(unit), 201)


@bp.route("/engine-units/<unit_id>", methods=["GET"])
@endpoint(READ_ROLES)
def read_unit(unit_id):
    unit = svc.get_engine_unit(unit_id)
    return object_response(store.public(unit), 200)


@bp.route("/engine-units", methods=["GET"])
@endpoint(READ_ROLES)
def list_units():
    limit, offset = v.pagination()
    order_id = v.query_string("build_order_id")
    run_id = v.query_string("machining_run_id")
    carburetor_lot_id = v.query_string("carburetor_lot_id")
    ignition_lot_id = v.query_string("ignition_lot_id")
    build_state = v.query_enum("build_state", BUILD_STATES)
    conformance_state = v.query_enum("conformance_state", CONFORMANCE_STATES)
    rows = store.sort_created_asc(list(db.engine_units.values()))
    if order_id is not None:
        rows = [r for r in rows if r["build_order_id"] == order_id]
    if run_id is not None:
        rows = [r for r in rows if r["machining_run_id"] == run_id]
    if carburetor_lot_id is not None:
        rows = [r for r in rows if r["carburetor_lot_id"] == carburetor_lot_id]
    if ignition_lot_id is not None:
        rows = [r for r in rows if r["ignition_lot_id"] == ignition_lot_id]
    if build_state is not None:
        rows = [r for r in rows if r["build_state"] == build_state]
    if conformance_state is not None:
        rows = [r for r in rows if r["conformance_state"] == conformance_state]
    page, total = v.paginate(rows, limit, offset)
    return list_response([store.public(r) for r in page], limit, offset, total)


# ------------------------------------------------------------ torque and hot test

@bp.route("/engine-units/<unit_id>/torque-record", methods=["POST"])
@endpoint(["QualityEngineer"])
def record_torque(unit_id):
    payload = v.body()
    raw = v.array_field(payload, "torque_readings")
    readings = []
    for entry in raw:
        if not isinstance(entry, dict):
            v.bad("Each entry of 'torque_readings' must be an object.")
        station = v.int_field(entry, "station")
        torque_nm = v.number_field(entry, "torque_nm")
        readings.append({"station": station, "torque_nm": torque_nm})

    unit = svc.get_engine_unit(unit_id)
    if unit["build_state"] != "STAGED":
        raise ApiError(
            "ERR_UNIT_STATE_INVALID",
            "Torque may only be recorded against a STAGED unit.",
        )
    if unit["conformance_state"] not in ("PENDING", "NONCONFORMING"):
        raise ApiError(
            "ERR_UNIT_NONCONFORMING",
            "The unit's conformance standing does not admit further progress.",
        )

    platform = _unit_platform(unit)
    required = platform["required_fastener_count"] if platform else None
    if required is None or len(readings) != required:
        raise ApiError(
            "ERR_TORQUE_READING_COUNT_MISMATCH",
            "Exactly %s torque readings are required." % required,
        )

    lower, upper = calc.torque_band(
        platform["torque_spec_nm"], platform["torque_tolerance_pct"]
    )
    out_of_spec = calc.out_of_spec_count(readings, lower, upper)
    set_fields(
        unit,
        torque_readings=readings,
        out_of_spec_fastener_count=out_of_spec,
        build_state="ASSEMBLED",
        conformance_state="NONCONFORMING" if out_of_spec > 0 else "PENDING",
    )
    return object_response(store.public(unit), 200)


@bp.route("/engine-units/<unit_id>/hot-test", methods=["POST"])
@endpoint(["QualityEngineer"])
def hot_test(unit_id):
    payload = v.body()
    measured_rpm = v.int_field(payload, "measured_rpm", 0, 10000)
    measured_emission = v.number_field(payload, "measured_emission_g_per_kwh", exclusive_min=0)

    unit = svc.get_engine_unit(unit_id)
    if unit["build_state"] != "ASSEMBLED":
        raise ApiError(
            "ERR_UNIT_STATE_INVALID",
            "The hot test may only be run against an ASSEMBLED unit.",
        )
    if unit["conformance_state"] != "PENDING":
        raise ApiError(
            "ERR_UNIT_NONCONFORMING",
            "Only a unit whose conformance is PENDING may be hot-tested.",
        )

    platform = _unit_platform(unit)
    family = svc.platform_family(platform) if platform else None
    basis = None
    if family is not None:
        basis = family["certified_emission_g_per_kwh"]
        if basis is None:
            basis = family["family_emission_limit_g_per_kwh"]
    threshold = calc.hot_test_threshold(basis, unit["deviation_sourced"])

    rpm_ok = platform["hot_test_min_rpm"] <= measured_rpm <= platform["hot_test_max_rpm"]
    emission_ok = calc.dec(measured_emission) <= threshold
    set_fields(
        unit,
        measured_rpm=measured_rpm,
        measured_emission_g_per_kwh=measured_emission,
        hot_test_emission_threshold=threshold,
        build_state="HOT_TESTED",
        conformance_state="CONFORMING" if (rpm_ok and emission_ok) else "NONCONFORMING",
    )
    return object_response(store.public(unit), 200)


# ---------------------------------------------------- release, rework, cancel

@bp.route("/engine-units/<unit_id>/release", methods=["POST"])
@endpoint(["QualityEngineer"])
def release_unit(unit_id):
    v.body()
    unit = svc.get_engine_unit(unit_id)
    order = db.build_orders.get(unit["build_order_id"])

    if order is None or order["status"] not in ACCEPTING_ORDER_STATUSES:
        raise ApiError(
            "ERR_BUILD_ORDER_NOT_ACCEPTING_UNITS",
            "The build order is not accepting unit releases.",
        )
    if unit["build_state"] != "HOT_TESTED":
        raise ApiError(
            "ERR_UNIT_STATE_INVALID",
            "Only a HOT_TESTED unit may be released to finished goods.",
        )
    if unit["conformance_state"] != "CONFORMING":
        raise ApiError(
            "ERR_UNIT_NONCONFORMING",
            "Only a CONFORMING unit may be released to finished goods.",
        )

    set_fields(unit, build_state="RELEASED", released_at=store.now_clock())

    units = svc.units_of_order(order["id"])
    built = len([u for u in units if u["build_state"] == "RELEASED"])
    completed = built >= order["planned_quantity"]
    _sync_order(order, "COMPLETED" if completed else None)
    return object_response(store.public(unit), 200)


@bp.route("/engine-units/<unit_id>/rework", methods=["POST"])
@endpoint(["QualityEngineer"])
def rework_unit(unit_id):
    v.body()
    unit = svc.get_engine_unit(unit_id)
    if unit["build_state"] not in ("ASSEMBLED", "HOT_TESTED"):
        raise ApiError(
            "ERR_UNIT_STATE_INVALID",
            "Only an ASSEMBLED or HOT_TESTED unit may be reworked.",
        )
    if unit["conformance_state"] != "NONCONFORMING":
        raise ApiError(
            "ERR_UNIT_NONCONFORMING",
            "Only a NONCONFORMING unit may be reworked.",
        )
    if unit["rework_count"] >= calc.MAX_REWORK_CYCLES:
        raise ApiError(
            "ERR_REWORK_LIMIT_EXCEEDED",
            "The unit has exhausted its rework allowance.",
        )

    set_fields(
        unit,
        rework_count=unit["rework_count"] + 1,
        build_state="STAGED",
        conformance_state="PENDING",
        torque_readings=None,
        out_of_spec_fastener_count=None,
        measured_rpm=None,
        measured_emission_g_per_kwh=None,
        hot_test_emission_threshold=None,
    )
    return object_response(store.public(unit), 200)


@bp.route("/engine-units/<unit_id>/cancel", methods=["POST"])
@endpoint(["QualityEngineer"])
def cancel_unit(unit_id):
    v.body()
    unit = svc.get_engine_unit(unit_id)
    if unit["build_state"] not in ("STAGED", "ASSEMBLED", "HOT_TESTED"):
        raise ApiError(
            "ERR_UNIT_STATE_INVALID",
            "Only an unreleased unit may be cancelled.",
        )

    set_fields(unit, build_state="CANCELLED")

    for lot_id in (unit["carburetor_lot_id"], unit["ignition_lot_id"]):
        lot = db.component_lots.get(lot_id)
        if lot is None:
            continue
        set_fields(
            lot,
            consumed_qty=lot["consumed_qty"] - 1,
            remaining_qty=lot["remaining_qty"] + 1,
        )

    order = db.build_orders.get(unit["build_order_id"])
    if order is not None:
        _sync_order(order)
    return object_response(store.public(unit), 200)
