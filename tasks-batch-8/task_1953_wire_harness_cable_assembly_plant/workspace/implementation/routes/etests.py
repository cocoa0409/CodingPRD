"""Electrical test records: continuity and hipot (PRD 3.7)."""
from flask import Blueprint, request

from db import db
from errors import (raise_error, ERR_INVALID_REQUEST, ERR_HARNESS_NOT_TESTABLE,
                    ERR_OPERATOR_NOT_CERTIFIED, ERR_SOD_BUILDER_CANNOT_TEST,
                    ERR_HIPOT_VOLTAGE_BELOW_CLASS_MIN)
from middleware import authenticate, ALL_ROLES
from response import success_object
from services import (TEST_TYPES, HIPOT_CLASS_MIN_V, record_fields, touch,
                      has_active_cert, completion_check,
                      ser_electrical_test, paginated)
from util import CLOCK, dec
from validate import get_body, req_str, req_int, req_num, req_enum, require_path

bp = Blueprint("electrical_test_records", __name__)

QUALITY_INSPECTOR = {"QualityInspector"}

TESTABLE_STATUSES = ("BUILT", "REWORK", "SUSPECT")


@bp.route("/plant/electrical-test-records", methods=["POST"])
def create_electrical_test():
    body = get_body()
    # Tier 1 (incl. conditional requirements per test_type).
    harness_unit_id = req_str(body, "harness_unit_id")
    test_type = req_enum(body, "test_type", TEST_TYPES)
    opens_count = None
    hipot_voltage_v = dwell_seconds = measured_leakage_ua = leakage_limit_ua = None
    if test_type == "CONTINUITY":
        opens_count = req_int(body, "opens_count", minimum=0)
    else:  # HIPOT
        hipot_voltage_v = req_num(body, "hipot_voltage_v")
        dwell_seconds = req_num(body, "dwell_seconds")
        measured_leakage_ua = req_num(body, "measured_leakage_ua")
        leakage_limit_ua = req_num(body, "leakage_limit_ua")
    # Tiers 2-3
    caller = authenticate(QUALITY_INSPECTOR)
    # Tier 4
    unit = require_path("harness_units", harness_unit_id)
    # Tier 6
    if unit["status"] not in TESTABLE_STATUSES:
        raise_error(ERR_HARNESS_NOT_TESTABLE,
                    "unit must be BUILT, REWORK, or SUSPECT for electrical testing")
    order = db["build_orders"][unit["build_order_id"]]
    # Tier 7, fixed internal order: certification -> segregation of duties ->
    # hipot voltage floor (PRD 2.6).
    if not has_active_cert(caller.user_id, order["workmanship_class"]):
        raise_error(ERR_OPERATOR_NOT_CERTIFIED,
                    "acting inspector lacks an ACTIVE certification for the "
                    "order's workmanship class")
    if caller.user_id == unit["built_by_operator_id"]:
        raise_error(ERR_SOD_BUILDER_CANNOT_TEST,
                    "the builder of a harness may not record its electrical test")
    if test_type == "HIPOT" and \
            dec(hipot_voltage_v) < dec(HIPOT_CLASS_MIN_V[order["workmanship_class"]]):
        raise_error(ERR_HIPOT_VOLTAGE_BELOW_CLASS_MIN,
                    "hipot_voltage_v below the workmanship-class minimum")

    # electrical_test_result: continuity PASS iff zero opens; hipot PASS iff
    # leakage at most the limit (inclusive boundary).
    if test_type == "CONTINUITY":
        result = "PASS" if opens_count == 0 else "FAIL"
    else:
        result = "PASS" if dec(measured_leakage_ua) <= dec(leakage_limit_ua) else "FAIL"

    now = CLOCK.now()
    record = record_fields()
    record.update({
        "harness_unit_id": unit["id"],
        "test_operator_id": caller.user_id,
        "test_type": test_type,
        "opens_count": opens_count,
        "hipot_voltage_v": hipot_voltage_v,
        "dwell_seconds": dwell_seconds,
        "measured_leakage_ua": measured_leakage_ua,
        "leakage_limit_ua": leakage_limit_ua,
        "result": result,
        "tested_at": now,
    })
    db["electrical_test_records"][record["id"]] = record

    if result == "PASS":
        if test_type == "CONTINUITY":
            unit["continuity_pass"] = True
            unit["_continuity_pass_at"] = now
        else:
            unit["hipot_pass"] = True
            unit["_hipot_pass_at"] = now
        advanced = False
        if unit["status"] == "BUILT" and unit["continuity_pass"] and unit["hipot_pass"]:
            unit["status"] = "TEST_PASS"
            advanced = True
        elif unit["status"] == "SUSPECT" and unit["continuity_pass"] and unit["hipot_pass"]:
            # SUSPECT -> TEST_PASS requires both passing records to carry
            # tested_at at or after suspect_marked_at (PRD 3.7).
            marked = unit["suspect_marked_at"]
            if marked is None or (
                    unit["_continuity_pass_at"] is not None
                    and unit["_hipot_pass_at"] is not None
                    and unit["_continuity_pass_at"] >= marked
                    and unit["_hipot_pass_at"] >= marked):
                unit["status"] = "TEST_PASS"
                unit["suspect_marked_at"] = None
                advanced = True
        touch(unit)
        if advanced:
            completion_check(order)
    else:
        # Any FAIL drives BUILT|REWORK|SUSPECT into REWORK; only the failed
        # test type's flag resets; suspect_marked_at clears if set.
        unit["status"] = "REWORK"
        if test_type == "CONTINUITY":
            unit["continuity_pass"] = False
            unit["_continuity_pass_at"] = None
        else:
            unit["hipot_pass"] = False
            unit["_hipot_pass_at"] = None
        unit["suspect_marked_at"] = None
        touch(unit)

    return success_object(ser_electrical_test(record), 201)


@bp.route("/plant/electrical-test-records/<tid>", methods=["GET"])
def get_electrical_test(tid):
    authenticate(ALL_ROLES)
    record = require_path("electrical_test_records", tid)
    return success_object(ser_electrical_test(record), 200)


@bp.route("/plant/electrical-test-records", methods=["GET"])
def list_electrical_tests():
    authenticate(ALL_ROLES)
    items = list(db["electrical_test_records"].values())
    harness_unit_id = request.args.get("harness_unit_id")
    if harness_unit_id is not None:
        items = [t for t in items if t["harness_unit_id"] == harness_unit_id]
    test_operator_id = request.args.get("test_operator_id")
    if test_operator_id is not None:
        items = [t for t in items if t["test_operator_id"] == test_operator_id]
    return paginated(items, ser_electrical_test)
