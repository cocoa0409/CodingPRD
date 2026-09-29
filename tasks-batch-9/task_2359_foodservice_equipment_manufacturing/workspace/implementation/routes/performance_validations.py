"""PerformanceValidation endpoints (PRD Section 3.4)."""
from flask import Blueprint

import validate
from db import db, insert, touch, ordered
from errors import ApiError
from middleware import authorize
from response import ok, created, ok_list
from routes.helpers import find, filter_by
from services import calc

bp = Blueprint("performance_validations", __name__)

STATUSES = ("IN_PROGRESS", "PASSED", "FAILED", "SUPERSEDED")
ROLES = ("ApplicationEngineer", "EngineeringApprover", "ChainAdmin", "PlatformAdmin")


@bp.post("/performance-validations")
def create_validation():
    authorize("ApplicationEngineer", "PlatformAdmin")
    payload = validate.body()
    chain_configuration_id = validate.string_field(payload, "chain_configuration_id")
    menu_item_code = validate.string_field(payload, "menu_item_code", min_len=1, max_len=32)
    target = validate.number_field(payload, "target_throughput_units_per_hour", gt=0)
    hold_temp_target_c = validate.number_field(payload, "hold_temp_target_c", gt=0)
    expected_version = validate.int_field(payload, "expected_chain_configuration_version")

    config = find(db.chain_configurations, chain_configuration_id,
                  "ERR_CHAIN_RESOURCE_NOT_FOUND")
    model = db.equipment_models[config["equipment_model_id"]]

    # the target may not exceed the catalogue's rated throughput (malformed request)
    if calc.dec(target) > calc.dec(model["rated_throughput_units_per_hour"]):
        validate.bad("'target_throughput_units_per_hour' exceeds the model's rated throughput")

    if expected_version != config["version"]:
        raise ApiError("ERR_STALE_CONFIGURATION_VERSION",
                       "expected_chain_configuration_version %s does not match %s"
                       % (expected_version, config["version"]))

    if config["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_CONFIGURATION_STATE_INVALID",
                       "a validation cannot be opened while the configuration is %s"
                       % config["status"])

    for sibling in ordered(db.performance_validations):
        if sibling["chain_configuration_id"] != chain_configuration_id:
            continue
        if sibling["menu_item_code"] != menu_item_code:
            continue
        if sibling["status"] in ("IN_PROGRESS", "PASSED", "FAILED"):
            sibling["status"] = "SUPERSEDED"
            touch(sibling)

    validation = insert(db.performance_validations, {
        "chain_configuration_id": chain_configuration_id,
        "menu_item_code": menu_item_code,
        "target_throughput_units_per_hour": target,
        "hold_temp_target_c": hold_temp_target_c,
        "status": "IN_PROGRESS",
        "attempt_count": 0,
        "test_runs": [],
        "certified_throughput_units_per_hour": None,
        "as_tested_throughput_units_per_hour": None,
        "failure_reason": None,
    })

    touch(config)  # opening a validation increments the parent configuration's version
    return created(validation)


@bp.get("/performance-validations")
def list_validations():
    authorize(*ROLES)
    limit, offset = validate.pagination()
    chain_configuration_id = validate.str_arg("chain_configuration_id")
    menu_item_code = validate.str_arg("menu_item_code")
    status = validate.enum_arg("status", STATUSES)

    items = ordered(db.performance_validations)
    items = filter_by(items, "chain_configuration_id", chain_configuration_id)
    items = filter_by(items, "menu_item_code", menu_item_code)
    items = filter_by(items, "status", status)
    return ok_list(items, limit, offset)


@bp.get("/performance-validations/<validation_id>")
def get_validation(validation_id):
    authorize(*ROLES)
    validation = find(db.performance_validations, validation_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")
    return ok(validation)


@bp.post("/performance-validations/<validation_id>/test-runs")
def append_test_run(validation_id):
    authorize("ApplicationEngineer", "PlatformAdmin")
    payload = validate.body()
    units_produced = validate.int_field(payload, "units_produced", minimum=0)
    minutes = validate.number_field(payload, "minutes", gt=0)
    hold_temp_c = validate.number_field(payload, "hold_temp_c")

    validation = find(db.performance_validations, validation_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")
    if validation["status"] != "IN_PROGRESS":
        raise ApiError("ERR_VALIDATION_STATE_INVALID",
                       "test runs cannot be appended to a %s validation" % validation["status"])

    validation["test_runs"].append({
        "run_index": len(validation["test_runs"]) + 1,
        "units_produced": units_produced,
        "minutes": minutes,
        "hold_temp_c": hold_temp_c,
        "recorded_at": db.clock,
    })
    touch(validation)
    return ok(validation)


@bp.post("/performance-validations/<validation_id>/conclusion")
def conclude_validation(validation_id):
    authorize("ApplicationEngineer", "PlatformAdmin")
    validation = find(db.performance_validations, validation_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")

    if validation["status"] != "IN_PROGRESS":
        raise ApiError("ERR_VALIDATION_STATE_INVALID",
                       "a %s validation cannot be concluded" % validation["status"])
    if validation["attempt_count"] >= calc.RETEST_LIMIT:
        raise ApiError("ERR_RETEST_LIMIT_EXCEEDED", "the attempt budget is exhausted")
    if len(validation["test_runs"]) < calc.MIN_RUNS:
        raise ApiError("ERR_MIN_TEST_RUNS_NOT_MET",
                       "at least %d test runs are required" % calc.MIN_RUNS)

    certified, as_tested = calc.measured_throughput(validation["test_runs"])
    validation["attempt_count"] += 1
    validation["certified_throughput_units_per_hour"] = float(certified)
    validation["as_tested_throughput_units_per_hour"] = float(as_tested)

    throughput_ok = certified >= calc.dec(validation["target_throughput_units_per_hour"])
    hold_ok = calc.hold_temp_within_tolerance(validation["test_runs"],
                                              validation["hold_temp_target_c"])
    if throughput_ok and hold_ok:
        validation["status"] = "PASSED"
        validation["failure_reason"] = None
    else:
        validation["status"] = "FAILED"
        validation["failure_reason"] = ("THROUGHPUT_BELOW_TARGET" if not throughput_ok
                                       else "HOLD_TEMP_OUT_OF_TOLERANCE")
    touch(validation)
    return ok(validation)


@bp.post("/performance-validations/<validation_id>/retest")
def retest_validation(validation_id):
    authorize("ApplicationEngineer", "PlatformAdmin")
    validation = find(db.performance_validations, validation_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")

    if validation["status"] != "FAILED":
        raise ApiError("ERR_VALIDATION_STATE_INVALID",
                       "only a FAILED validation can be retested")
    if validation["attempt_count"] >= calc.RETEST_LIMIT:
        raise ApiError("ERR_RETEST_LIMIT_EXCEEDED", "the attempt budget is exhausted")

    config = db.chain_configurations[validation["chain_configuration_id"]]
    if config["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_CONFIGURATION_STATE_INVALID",
                       "a validation cannot be retested while the configuration is %s"
                       % config["status"])

    validation["status"] = "IN_PROGRESS"
    validation["test_runs"] = []
    validation["certified_throughput_units_per_hour"] = None
    validation["as_tested_throughput_units_per_hour"] = None
    validation["failure_reason"] = None
    touch(validation)
    return ok(validation)
