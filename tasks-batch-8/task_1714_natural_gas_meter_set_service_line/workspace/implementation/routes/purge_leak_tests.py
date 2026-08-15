"""PurgeLeakTest endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ERR_INSPECTOR_NOT_CERTIFIED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SOD_WITNESS_IS_INSTALLER,
    ERR_TEST_ALREADY_ACTIVE,
    ERR_TEST_PARAMS_UNSAFE,
    raise_error,
)
from middleware import (
    ANY_ROLE,
    check_app_mutable,
    get_body,
    new_id,
    paginate,
    require_fields,
    require_int,
    require_number,
    require_roles,
    require_str,
)
from response import success_list, success_object
from services.calculations import leak_test_acceptance
from services.domain import (
    get_application,
    get_inspector,
    get_meter_set,
    get_test,
    tests_for_meter_set,
    touch,
)

bp = Blueprint("purge_leak_tests", __name__)


@bp.route("/purge-leak-tests", methods=["POST"])
def create_test():
    user_id, _ = require_roles("MeterTechnician")
    body = get_body()
    require_fields(
        body,
        "meter_set_id",
        "purge_duration_min",
        "test_pressure_psi",
        "test_duration_min",
        "observed_pressure_drop_psi",
    )
    ms = get_meter_set(body["meter_set_id"])
    purge_duration = require_int(body, "purge_duration_min")
    test_pressure = require_number(body, "test_pressure_psi")
    test_duration = require_int(body, "test_duration_min")
    observed_drop = require_number(body, "observed_pressure_drop_psi")
    app = get_application(ms["service_application_id"])
    check_app_mutable(app)
    # Safety minima (priority 8)
    if purge_duration < 5 or test_pressure < 10.0 or test_duration < 15:
        raise_error(ERR_TEST_PARAMS_UNSAFE, "Purge/leak test parameters below safety minima")
    # One RECORDED test per meter set at a time — a RECORDED test implies the meter
    # is in TESTING, so this check precedes the INSTALLED/REPAIR state gate to surface
    # the catalogued ERR_TEST_ALREADY_ACTIVE (SCAFFOLD MeterSet INSTALLED→TESTING
    # precondition / error catalog).
    if any(t["status"] == "RECORDED" for t in tests_for_meter_set(ms["id"])):
        raise_error(ERR_TEST_ALREADY_ACTIVE, "A RECORDED test already exists for this meter set")
    if ms["status"] not in ("INSTALLED", "REPAIR"):
        raise_error(ERR_INVALID_STATE, "Meter set must be INSTALLED (or REPAIR) to record a test")
    max_allowed, result = leak_test_acceptance(test_duration, observed_drop)
    now = db.now_iso()
    test = {
        "id": new_id(),
        "meter_set_id": ms["id"],
        "installer_user_id": user_id,
        "purge_duration_min": purge_duration,
        "test_pressure_psi": test_pressure,
        "test_duration_min": test_duration,
        "observed_pressure_drop_psi": observed_drop,
        "max_allowed_drop_psi": max_allowed,
        "result": result,
        "status": "RECORDED",
        "witness_inspector_id": None,
        "rejection_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.purge_leak_tests[test["id"]] = test
    # MeterSet INSTALLED|REPAIR → TESTING; application METER_WORK → TESTING
    ms["status"] = "TESTING"
    touch(ms)
    if app["status"] == "METER_WORK":
        app["status"] = "TESTING"
        touch(app)
    return success_object(test, 201)


@bp.route("/purge-leak-tests/<tid>", methods=["GET"])
def get_one_test(tid):
    require_roles(*ANY_ROLE)
    return success_object(get_test(tid))


@bp.route("/purge-leak-tests", methods=["GET"])
def list_tests():
    require_roles(*ANY_ROLE)
    records = list(db.purge_leak_tests.values())
    ms_id = request.args.get("meter_set_id")
    if ms_id is not None:
        records = [t for t in records if t["meter_set_id"] == ms_id]
    page, limit, offset, total = paginate(records)
    return success_list(page, limit, offset, total)


@bp.route("/purge-leak-tests/<tid>/certify", methods=["POST"])
def certify_test(tid):
    user_id, _ = require_roles("Inspector")
    test = get_test(tid)
    ms = get_meter_set(test["meter_set_id"])
    app = get_application(ms["service_application_id"])
    check_app_mutable(app)
    if test["status"] != "RECORDED":
        raise_error(ERR_INVALID_STATE, "Only RECORDED tests can be certified")
    # Witness must be an existing inspector, PRESSURE_TEST-certified, and not the installer
    witness = get_inspector(user_id)
    if "PRESSURE_TEST" not in witness["certifications"]:
        raise_error(ERR_INSPECTOR_NOT_CERTIFIED, "Witness lacks the PRESSURE_TEST certification")
    if user_id == test["installer_user_id"]:
        raise_error(ERR_SOD_WITNESS_IS_INSTALLER, "The installer may not witness-certify their own test")
    test["witness_inspector_id"] = user_id
    test["status"] = "CERTIFIED"
    touch(test)
    if test["result"] == "PASS":
        # Link 1: meter TESTING → READY_FOR_TURN_ON; Link 2: app TESTING → TURN_ON
        if ms["status"] == "TESTING":
            ms["status"] = "READY_FOR_TURN_ON"
            touch(ms)
        if app["status"] == "TESTING":
            app["status"] = "TURN_ON"
            touch(app)
    else:
        if ms["status"] == "TESTING":
            ms["status"] = "REPAIR"
            touch(ms)
    return success_object(test)


@bp.route("/purge-leak-tests/<tid>/reject", methods=["POST"])
def reject_test(tid):
    user_id, _ = require_roles("Inspector")
    test = get_test(tid)
    ms = get_meter_set(test["meter_set_id"])
    app = get_application(ms["service_application_id"])
    body = get_body()
    require_fields(body, "rejection_reason")
    reason = require_str(body, "rejection_reason")
    check_app_mutable(app)
    if test["status"] != "RECORDED":
        raise_error(ERR_INVALID_STATE, "Only RECORDED tests can be rejected")
    test["rejection_reason"] = reason
    test["status"] = "REJECTED"
    touch(test)
    # Meter set remains TESTING — a fresh test may be recorded
    return success_object(test)
