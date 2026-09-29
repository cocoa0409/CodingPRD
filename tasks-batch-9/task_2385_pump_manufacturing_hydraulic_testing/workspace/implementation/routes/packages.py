"""Engineered pump packages: motor sizing, guarantee basis and shipment."""

from flask import Blueprint

from db import by_seq, db, new_record
from errors import ApiError
from helpers import (
    apply_filters,
    duty_of_selection,
    paginate,
    path_lookup,
    ref_lookup,
    selection_of_build,
    touch,
)
from middleware import ALL_ROLES, authorize
from response import list_response, object_response
from serializers import dump, dump_all
from services import calc
from services.cascades import recompute_committed_build_count
from validation import (
    CONTROL_TYPES,
    check_keys,
    get_body,
    pagination,
    query_value,
    req_datetime,
    req_enum,
    req_number,
    req_string,
)

bp = Blueprint("packages", __name__)


def _no_body_allowed():
    check_keys(get_body(), ())


def _collection(records, limit, offset):
    window, total = paginate(records, limit, offset)
    return list_response(dump_all(window), limit, offset, total)


@bp.post("/pump-packages")
def create_pump_package():
    authorize("ProductionPlanner")
    body = get_body()
    check_keys(
        body,
        (
            "build_order_id",
            "test_run_id",
            "baseplate_code",
            "motor_kw",
            "motor_frame",
            "control_type",
            "promised_ship_date",
        ),
    )
    build_order_id = req_string(body, "build_order_id")
    test_run_id = req_string(body, "test_run_id")
    baseplate_code = req_string(body, "baseplate_code")
    motor_kw = req_number(body, "motor_kw", exclusive_min=0)
    motor_frame = req_string(body, "motor_frame")
    control_type = req_enum(body, "control_type", CONTROL_TYPES)
    promised_ship_date = req_datetime(body, "promised_ship_date")

    order = ref_lookup(db.build_orders, build_order_id)
    run = ref_lookup(db.test_runs, test_run_id)

    selection = selection_of_build(order)

    # Rung 23: the named run must already be evaluated so that the witnessed
    # reference power exists. Only the witnessed basis reads it.
    if run["witness_required"] and run["power_at_guarantee_kw"] is None:
        raise ApiError("ERR_TEST_RUN_NOT_CERTIFIED")
    if order["status"] != "TESTED":
        raise ApiError("ERR_BUILD_ORDER_NOT_TESTED")
    if run["build_order_id"] != order["id"]:
        raise ApiError("ERR_TEST_RUN_BUILD_MISMATCH")

    if run["witness_required"]:
        reference_power = calc.D(run["power_at_guarantee_kw"])
    else:
        reference_power = calc.D(selection["predicted_shaft_power_kw"])
    min_motor_kw = calc.rhu(reference_power * calc.MOTOR_SERVICE_FACTOR, 2)
    if calc.D(motor_kw) < min_motor_kw:
        raise ApiError("ERR_MOTOR_UNDERSIZED")

    record = new_record(
        "PumpPackage",
        build_order_id=build_order_id,
        test_run_id=test_run_id,
        baseplate_code=baseplate_code,
        motor_kw=motor_kw,
        motor_frame=motor_frame,
        control_type=control_type,
        promised_ship_date=promised_ship_date,
        actual_ship_date=None,
        min_motor_kw=min_motor_kw,
        guarantee_basis=None,
        application_error_flagged=False,
        status="CONFIGURED",
    )
    db.pump_packages[record["id"]] = record
    return object_response(dump(record), 201)


@bp.get("/pump-packages")
def list_pump_packages():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    records = apply_filters(
        by_seq(db.pump_packages.values()),
        [
            (query_value("build_order_id"), "build_order_id"),
            (query_value("test_run_id"), "test_run_id"),
            (query_value("status"), "status"),
        ],
    )
    return _collection(records, limit, offset)


@bp.get("/pump-packages/<resource_id>")
def read_pump_package(resource_id):
    authorize(*ALL_ROLES)
    return object_response(dump(path_lookup(db.pump_packages, resource_id)))


@bp.post("/pump-packages/<resource_id>/release")
def release_pump_package(resource_id):
    authorize("ProductionPlanner")
    _no_body_allowed()
    package = path_lookup(db.pump_packages, resource_id)
    if package["status"] != "CONFIGURED":
        raise ApiError("ERR_PACKAGE_INVALID_STATE")
    run = db.test_runs.get(package["test_run_id"])
    if run is None or run["run_state"] != "CERTIFIED":
        raise ApiError("ERR_TEST_RUN_NOT_CERTIFIED")

    package["status"] = "RELEASED"
    package["guarantee_basis"] = "CERTIFIED_CURVE" if run["witness_required"] else "SELECTION"
    touch(package)
    return object_response(dump(package))


@bp.post("/pump-packages/<resource_id>/ship")
def ship_pump_package(resource_id):
    authorize("ProductionPlanner")
    body = get_body()
    check_keys(body, ("actual_ship_date",))
    actual_ship_date = req_datetime(body, "actual_ship_date")

    package = path_lookup(db.pump_packages, resource_id)
    if package["status"] != "RELEASED":
        raise ApiError("ERR_PACKAGE_INVALID_STATE")

    package["status"] = "SHIPPED"
    package["actual_ship_date"] = actual_ship_date
    touch(package)

    order = db.build_orders.get(package["build_order_id"])
    if order is not None and order["status"] == "TESTED":
        order["status"] = "CLOSED"
        touch(order)
        lot = db.casting_lots.get(order["casting_lot_id"])
        if lot is not None:
            recompute_committed_build_count(lot)
            touch(lot)
        duty = duty_of_selection(selection_of_build(order))
        if duty is not None and duty["status"] == "CONTRACTED":
            duty["status"] = "CLOSED"
            touch(duty)
    return object_response(dump(package))


@bp.post("/pump-packages/<resource_id>/release-hold")
def release_hold(resource_id):
    authorize("ProductionPlanner")
    _no_body_allowed()
    package = path_lookup(db.pump_packages, resource_id)
    order = db.build_orders.get(package["build_order_id"])
    # Rung 17 orders the build order ahead of the package, so a still-stranded
    # order is reported before the package's own state.
    if order is not None and order["status"] == "CASTING_SHORT":
        raise ApiError("ERR_BUILD_ORDER_INVALID_STATE")
    if package["status"] != "HELD":
        raise ApiError("ERR_PACKAGE_INVALID_STATE")
    package["status"] = "CONFIGURED"
    touch(package)
    return object_response(dump(package))
