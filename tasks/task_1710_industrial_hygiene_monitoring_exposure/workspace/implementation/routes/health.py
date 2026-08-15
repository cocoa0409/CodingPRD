"""Medical clearances and respirator fit tests (PRD section 3.8)."""

from flask import Blueprint, request

import db
from errors import (
    ERR_CLEARANCE_EMPLOYEE_MISMATCH,
    ERR_CLEARANCE_INVALID_STATE,
    ERR_FIT_TEST_NOT_RECORDABLE,
    ERR_MEDICAL_CLEARANCE_NOT_CURRENT,
    raise_error,
)
from helpers import (
    reject_unknown,
    body, get_or_404, list_response, now_ts, req_date, req_enum, req_string,
    stamp_new, today, touch,
)
from middleware import ALL_ROLES, require_auth
from response import success_object
from serializers import clearance_out, fit_test_out
from services import add_days

bp = Blueprint("health", __name__)

SSM = ("SiteSafetyManager",)
CIH = ("CIHDirector",)
TECH = ("FieldTechnician",)


# ---------------------------------------------------------------------------
# Medical clearances
# ---------------------------------------------------------------------------

@bp.route("/ih/medical-clearances", methods=["POST"])
def create_clearance():
    require_auth(SSM)
    data = body()
    reject_unknown(data, {"employee_id"})
    employee_id = req_string(data, "employee_id")
    get_or_404(db.employees, employee_id, "Employee")
    clearance = {
        "employee_id": employee_id,
        "status": "REQUESTED",
        "decided_at": None,
        "expiry_date": None,
        "decided_by_user_id": None,
    }
    stamp_new(clearance)
    db.medical_clearances[clearance["id"]] = clearance
    return success_object(clearance_out(clearance), 201)


@bp.route("/ih/medical-clearances", methods=["GET"])
def list_clearances():
    require_auth(ALL_ROLES)
    return list_response(list(db.medical_clearances.values()), clearance_out,
                         {"employee_id": request.args.get("employee_id")})


@bp.route("/ih/medical-clearances/<cid>", methods=["GET"])
def get_clearance(cid):
    require_auth(ALL_ROLES)
    return success_object(clearance_out(get_or_404(db.medical_clearances, cid, "MedicalClearance")))


@bp.route("/ih/medical-clearances/<cid>/decide", methods=["POST"])
def decide_clearance(cid):
    user_id, _ = require_auth(CIH)
    data = body()
    reject_unknown(data, {"decision"})
    decision = req_enum(data, "decision", ("CLEARED", "DENIED"))
    clearance = get_or_404(db.medical_clearances, cid, "MedicalClearance")
    if clearance["status"] != "REQUESTED":
        raise_error(ERR_CLEARANCE_INVALID_STATE, "decide requires REQUESTED")
    clearance["decided_at"] = now_ts()
    clearance["decided_by_user_id"] = user_id
    clearance["status"] = decision
    if decision == "CLEARED":
        clearance["expiry_date"] = add_days(today(), 365).isoformat()
    touch(clearance)
    return success_object(clearance_out(clearance), 200)


# ---------------------------------------------------------------------------
# Respirator fit tests
# ---------------------------------------------------------------------------

@bp.route("/ih/fit-tests", methods=["POST"])
def create_fit_test():
    require_auth(SSM)
    data = body()
    reject_unknown(data, {"employee_id", "medical_clearance_id", "respirator_model", "test_date"})
    employee_id = req_string(data, "employee_id")
    medical_clearance_id = req_string(data, "medical_clearance_id")
    respirator_model = req_string(data, "respirator_model")
    test_date = req_date(data, "test_date")
    get_or_404(db.employees, employee_id, "Employee")
    clearance = get_or_404(db.medical_clearances, medical_clearance_id, "MedicalClearance")
    if clearance["employee_id"] != employee_id:
        raise_error(ERR_CLEARANCE_EMPLOYEE_MISMATCH,
                    "medical_clearance_id belongs to a different employee")
    fit_test = {
        "employee_id": employee_id,
        "medical_clearance_id": medical_clearance_id,
        "respirator_model": respirator_model,
        "test_date": test_date.isoformat(),
        "expiry_date": add_days(test_date, 365).isoformat(),
        "status": "SCHEDULED",
        "recorded_by_user_id": None,
    }
    stamp_new(fit_test)
    db.fit_tests[fit_test["id"]] = fit_test
    return success_object(fit_test_out(fit_test), 201)


@bp.route("/ih/fit-tests", methods=["GET"])
def list_fit_tests():
    require_auth(ALL_ROLES)
    return list_response(list(db.fit_tests.values()), fit_test_out, {
        "employee_id": request.args.get("employee_id"),
        "medical_clearance_id": request.args.get("medical_clearance_id"),
    })


@bp.route("/ih/fit-tests/<fid>", methods=["GET"])
def get_fit_test(fid):
    require_auth(ALL_ROLES)
    return success_object(fit_test_out(get_or_404(db.fit_tests, fid, "RespiratorFitTest")))


@bp.route("/ih/fit-tests/<fid>/record-result", methods=["POST"])
def record_result(fid):
    user_id, _ = require_auth(TECH)
    data = body()
    reject_unknown(data, {"result"})
    result = req_enum(data, "result", ("PASS", "FAIL"))
    fit_test = get_or_404(db.fit_tests, fid, "RespiratorFitTest")
    if fit_test["status"] != "SCHEDULED":
        raise_error(ERR_FIT_TEST_NOT_RECORDABLE, "record-result requires SCHEDULED")
    clearance = db.medical_clearances[fit_test["medical_clearance_id"]]
    from datetime import date as _date
    clearance_current = (clearance["status"] == "CLEARED"
                         and clearance["expiry_date"] is not None
                         and today() <= _date.fromisoformat(clearance["expiry_date"]))
    if not clearance_current:
        raise_error(ERR_MEDICAL_CLEARANCE_NOT_CURRENT,
                    "Linked clearance is not CLEARED or is past its expiry_date")
    fit_test["status"] = "PASSED" if result == "PASS" else "FAILED"
    fit_test["recorded_by_user_id"] = user_id
    touch(fit_test)
    return success_object(fit_test_out(fit_test), 200)
