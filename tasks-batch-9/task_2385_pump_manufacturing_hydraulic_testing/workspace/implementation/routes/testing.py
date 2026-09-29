"""Performance test runs, measured points, the certified curve and suction check."""

from flask import Blueprint

from db import by_seq, db, new_record
from errors import ApiError
from helpers import (
    apply_filters,
    duty_of_selection,
    model_of_selection,
    paginate,
    path_lookup,
    points_of_run,
    ref_lookup,
    selection_of_build,
    touch,
)
from middleware import ALL_ROLES, authorize
from response import list_response, object_response
from serializers import dump, dump_all
from services import calc
from services.cascades import cascade_rework_required
from validation import (
    CORRECTION_BASES,
    TEST_GRADES,
    check_keys,
    get_body,
    opt_bool,
    opt_number,
    pagination,
    present,
    query_value,
    req_bool,
    req_enum,
    req_int,
    req_number,
    req_string,
)

bp = Blueprint("testing", __name__)

REPORTED_FIELDS = (
    "speed_ratio",
    "head_at_guarantee_m",
    "power_at_guarantee_kw",
    "efficiency_at_guarantee_pct",
    "head_deviation_pct",
    "efficiency_deviation_pct",
    "npshr_tested_m",
)


def _no_body_allowed():
    check_keys(get_body(), ())


def _collection(records, limit, offset):
    window, total = paginate(records, limit, offset)
    return list_response(dump_all(window), limit, offset, total)


def _build_of_run(run):
    return db.build_orders.get(run["build_order_id"])


# --------------------------------------------------------------- test runs


@bp.post("/test-runs")
def create_test_run():
    authorize("TestEngineer")
    body = get_body()
    check_keys(
        body,
        ("build_order_id", "test_speed_rpm", "correction_basis", "test_grade", "witness_required"),
    )
    build_order_id = req_string(body, "build_order_id")
    test_speed = req_int(body, "test_speed_rpm", minimum=300)
    correction_basis = req_enum(body, "correction_basis", CORRECTION_BASES)
    test_grade = req_enum(body, "test_grade", TEST_GRADES)
    witness_required = req_bool(body, "witness_required")

    order = ref_lookup(db.build_orders, build_order_id)
    if order["status"] != "ASSEMBLED":
        raise ApiError("ERR_BUILD_ORDER_NOT_ASSEMBLED")

    record = new_record(
        "TestRun",
        build_order_id=build_order_id,
        test_speed_rpm=test_speed,
        correction_basis=correction_basis,
        test_grade=test_grade,
        witness_required=witness_required,
        speed_ratio=None,
        head_at_guarantee_m=None,
        power_at_guarantee_kw=None,
        efficiency_at_guarantee_pct=None,
        head_deviation_pct=None,
        efficiency_deviation_pct=None,
        npshr_tested_m=None,
        run_state="OPEN",
        hydraulic_status="NOT_EVALUATED",
        npsh_status="NOT_VERIFIED",
    )
    db.test_runs[record["id"]] = record
    return object_response(dump(record), 201)


@bp.get("/test-runs")
def list_test_runs():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    records = apply_filters(
        by_seq(db.test_runs.values()),
        [
            (query_value("build_order_id"), "build_order_id"),
            (query_value("run_state"), "run_state"),
            (query_value("hydraulic_status"), "hydraulic_status"),
            (query_value("npsh_status"), "npsh_status"),
        ],
    )
    return _collection(records, limit, offset)


@bp.get("/test-runs/<resource_id>")
def read_test_run(resource_id):
    authorize(*ALL_ROLES)
    return object_response(dump(path_lookup(db.test_runs, resource_id)))


# -------------------------------------------------------------- test points


@bp.post("/test-runs/<resource_id>/points")
def append_test_point(resource_id):
    authorize("TestEngineer")
    body = get_body()
    check_keys(
        body,
        (
            "measured_flow_m3h",
            "measured_head_m",
            "measured_power_kw",
            "measured_npsh3_m",
            "is_npsh_point",
        ),
    )
    measured_flow = req_number(body, "measured_flow_m3h", exclusive_min=0)
    measured_head = req_number(body, "measured_head_m", exclusive_min=0)
    measured_power = req_number(body, "measured_power_kw", exclusive_min=0)
    measured_npsh3 = opt_number(body, "measured_npsh3_m", exclusive_min=0)
    is_npsh_point = opt_bool(body, "is_npsh_point", False)
    if is_npsh_point and not present(body, "measured_npsh3_m"):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'measured_npsh3_m' is required when 'is_npsh_point' is true",
        )

    run = path_lookup(db.test_runs, resource_id)
    if run["run_state"] != "OPEN":
        raise ApiError("ERR_TEST_RUN_INVALID_STATE")

    record = new_record(
        "TestPoint",
        versioned=False,
        test_run_id=run["id"],
        measured_flow_m3h=measured_flow,
        measured_head_m=measured_head,
        measured_power_kw=measured_power,
        measured_npsh3_m=measured_npsh3,
        is_npsh_point=is_npsh_point,
    )
    db.test_points[record["id"]] = record
    return object_response(dump(record), 201)


@bp.get("/test-points")
def list_test_points():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    records = apply_filters(
        by_seq(db.test_points.values()), [(query_value("test_run_id"), "test_run_id")]
    )
    return _collection(records, limit, offset)


@bp.get("/test-points/<resource_id>")
def read_test_point(resource_id):
    authorize(*ALL_ROLES)
    return object_response(dump(path_lookup(db.test_points, resource_id)))


# ------------------------------------------------------------- transitions


@bp.post("/test-runs/<resource_id>/lock")
def lock_test_run(resource_id):
    authorize("TestEngineer")
    _no_body_allowed()
    run = path_lookup(db.test_runs, resource_id)
    if run["run_state"] != "OPEN":
        raise ApiError("ERR_TEST_RUN_INVALID_STATE")

    points = points_of_run(run["id"])
    minimum = calc.GRADE_TOLERANCES[run["test_grade"]]["min_points"]
    if len(points) < minimum:
        raise ApiError("ERR_INSUFFICIENT_TEST_POINTS")
    designated = [
        p for p in points if p["is_npsh_point"] and p["measured_npsh3_m"] is not None
    ]
    if len(designated) != 1:
        raise ApiError("ERR_NPSH_TEST_POINT_MISSING")

    run["run_state"] = "POINTS_LOCKED"
    touch(run)
    return object_response(dump(run))


@bp.post("/test-runs/<resource_id>/evaluate")
def evaluate_test_run(resource_id):
    authorize("TestEngineer")
    _no_body_allowed()
    run = path_lookup(db.test_runs, resource_id)
    if run["run_state"] != "POINTS_LOCKED":
        raise ApiError("ERR_TEST_RUN_INVALID_STATE")

    order = _build_of_run(run)
    selection = selection_of_build(order) if order is not None else None
    model = model_of_selection(selection)
    duty = duty_of_selection(selection)

    points = points_of_run(run["id"])
    factor, rows = calc.reported_points(model, run, points)
    guarantee_flow = calc.D(duty["duty_flow_m3h"])
    bracket = calc.interpolate(rows, guarantee_flow)
    if bracket is None:
        raise ApiError("ERR_GUARANTEE_FLOW_NOT_BRACKETED")
    head_at_guarantee = calc.rhu(bracket[0], 2)
    power_at_guarantee = calc.rhu(bracket[1], 2)

    efficiency = calc.rhu(
        calc.D(duty["specific_gravity"])
        * guarantee_flow
        * head_at_guarantee
        * calc.POWER_CONSTANT
        / power_at_guarantee
        * calc.HUNDRED,
        2,
    )
    predicted_head = calc.D(selection["predicted_head_m"])
    predicted_efficiency = calc.D(selection["predicted_efficiency_pct"])
    head_deviation = calc.rhu(
        (head_at_guarantee - predicted_head) / predicted_head * calc.HUNDRED, 2
    )
    efficiency_deviation = calc.rhu(
        (efficiency - predicted_efficiency) / predicted_efficiency * calc.HUNDRED, 2
    )
    npsh_row = [r for r in rows if r["point"]["is_npsh_point"]][0]
    npshr_tested = npsh_row["reported_npsh3_m"]

    run["speed_ratio"] = calc.rhu(factor, 4)
    run["head_at_guarantee_m"] = head_at_guarantee
    run["power_at_guarantee_kw"] = power_at_guarantee
    run["efficiency_at_guarantee_pct"] = efficiency
    run["head_deviation_pct"] = head_deviation
    run["efficiency_deviation_pct"] = efficiency_deviation
    run["npshr_tested_m"] = npshr_tested

    tolerances = calc.GRADE_TOLERANCES[run["test_grade"]]
    head_tolerance = tolerances["head_pct"]
    efficiency_tolerance = tolerances["eff_pct"]
    within = (
        -head_tolerance <= head_deviation <= head_tolerance
        and efficiency_deviation >= -efficiency_tolerance
    )
    run["hydraulic_status"] = "WITHIN_TOLERANCE" if within else "OUT_OF_TOLERANCE"

    npshr_catalog = calc.D(selection["npshr_catalog_m"])
    if npshr_tested <= npshr_catalog + calc.NPSH_TEST_TOLERANCE_M:
        run["npsh_status"] = "VERIFIED"
    else:
        run["npsh_status"] = "REJECTED"

    run["run_state"] = "EVALUATED"
    touch(run)

    if run["hydraulic_status"] == "OUT_OF_TOLERANCE":
        cascade_rework_required(order)
    return object_response(dump(run))


@bp.post("/test-runs/<resource_id>/certify")
def certify_test_run(resource_id):
    authorize("TestEngineer")
    _no_body_allowed()
    run = path_lookup(db.test_runs, resource_id)
    if run["run_state"] != "EVALUATED":
        raise ApiError("ERR_TEST_RUN_INVALID_STATE")
    if run["hydraulic_status"] != "WITHIN_TOLERANCE":
        raise ApiError("ERR_HYDRAULIC_OUT_OF_TOLERANCE")
    if run["npsh_status"] != "VERIFIED":
        raise ApiError("ERR_NPSH_NOT_VERIFIED")

    run["run_state"] = "CERTIFIED"
    touch(run)
    order = _build_of_run(run)
    if order is not None and order["status"] == "ASSEMBLED":
        order["status"] = "TESTED"
        touch(order)
    return object_response(dump(run))


@bp.post("/test-runs/<resource_id>/reopen")
def reopen_test_run(resource_id):
    authorize("TestEngineer")
    _no_body_allowed()
    run = path_lookup(db.test_runs, resource_id)
    if run["run_state"] != "EVALUATED":
        raise ApiError("ERR_TEST_RUN_INVALID_STATE")
    run["run_state"] = "OPEN"
    run["hydraulic_status"] = "NOT_EVALUATED"
    run["npsh_status"] = "NOT_VERIFIED"
    for field in REPORTED_FIELDS:
        run[field] = None
    touch(run)
    return object_response(dump(run))
