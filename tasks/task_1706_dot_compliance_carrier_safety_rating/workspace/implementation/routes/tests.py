"""DrugAlcoholTest endpoints (PRD 3.6): collection, lab report, MRO verification."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_MISSING_ACCIDENT_LINK, ERR_INVALID_DATE_RANGE,
    ERR_DRIVER_NOT_ACTIVE, ERR_DRIVER_NOT_SUSPENDED, ERR_FUTURE_OCCURRENCE,
    ERR_POST_ACCIDENT_WINDOW_MISSED, ERR_TEST_NOT_COLLECTED,
    ERR_TEST_NOT_LAB_REPORTED, ERR_SOD_VERIFIER_IS_RECORDER,
    ERR_VERDICT_RESULT_MISMATCH,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services.core import stamp_new, touch
from validate import (
    get_body, req_str, opt_str, req_enum, req_datetime,
    require_path_resource, require_ref,
)
from util import new_id, parse_datetime, CLOCK, fmt_datetime

bp = Blueprint("tests", __name__)

TEST_TYPES = [
    "PRE_EMPLOYMENT", "RANDOM", "POST_ACCIDENT", "REASONABLE_SUSPICION",
    "RETURN_TO_DUTY", "FOLLOW_UP",
]
SUBSTANCES = ["DRUG", "ALCOHOL"]
LAB_RESULTS = ["NEGATIVE", "POSITIVE", "REFUSAL", "CANCELLED_BY_LAB"]
VERDICTS = ["VERIFIED_NEGATIVE", "VERIFIED_POSITIVE", "VERIFIED_REFUSAL", "CANCELLED"]
SUSPENDED_REQUIRED_TYPES = ("RETURN_TO_DUTY", "FOLLOW_UP")
VERDICT_FOR_RESULT = {
    "NEGATIVE": "VERIFIED_NEGATIVE",
    "POSITIVE": "VERIFIED_POSITIVE",
    "REFUSAL": "VERIFIED_REFUSAL",
}
POST_ACCIDENT_WINDOW_HOURS = {"ALCOHOL": 8, "DRUG": 32}


@bp.post("/safety/drug-alcohol-tests")
def create_test():
    caller = authorized(["SafetyManager"])
    body = get_body()
    # Stage 3: shape (incl. conditional accident_id link, both directions)
    driver_id = req_str(body, "driver_id")
    test_type = req_enum(body, "test_type", TEST_TYPES)
    substance = req_enum(body, "substance", SUBSTANCES)
    collected_at = req_datetime(body, "collected_at")
    accident_id = body.get("accident_id")
    if test_type == "POST_ACCIDENT":
        if accident_id is None:
            raise_error(ERR_MISSING_ACCIDENT_LINK,
                        "accident_id is required for POST_ACCIDENT tests")
        if not isinstance(accident_id, str) or accident_id.strip() == "":
            raise_error(ERR_MISSING_ACCIDENT_LINK, "invalid accident_id")
    else:
        if accident_id is not None:
            raise_error(ERR_MISSING_ACCIDENT_LINK,
                        "accident_id is only allowed for POST_ACCIDENT tests")
    # Stage 4: body FK existence in declared input order
    driver = require_ref("drivers", driver_id, "driver_id")
    accident = None
    if accident_id is not None:
        accident = require_ref("accident_records", accident_id, "accident_id")
    # Stage 5: driver employment state per test type
    if test_type in SUSPENDED_REQUIRED_TYPES:
        if driver["employment_status"] != "SUSPENDED":
            raise_error(ERR_DRIVER_NOT_SUSPENDED,
                        f"{test_type} requires a SUSPENDED driver")
    else:
        if driver["employment_status"] != "ACTIVE":
            raise_error(ERR_DRIVER_NOT_ACTIVE, "test collection requires an ACTIVE driver")
    # Stage 8: temporal
    collected = parse_datetime(collected_at)
    if collected > CLOCK.now():
        raise_error(ERR_FUTURE_OCCURRENCE, "collected_at is in the future")
    if test_type == "POST_ACCIDENT" and accident is not None:
        occurred = parse_datetime(accident["occurred_at"])
        if collected < occurred:
            raise_error(ERR_INVALID_DATE_RANGE,
                        "collected_at precedes the accident's occurred_at")
        window = timedelta(hours=POST_ACCIDENT_WINDOW_HOURS[substance])
        if collected - occurred > window:
            raise_error(ERR_POST_ACCIDENT_WINDOW_MISSED,
                        f"POST_ACCIDENT {substance} collection exceeded the testing window")
    test = stamp_new({
        "id": new_id(),
        "driver_id": driver_id,
        "test_type": test_type,
        "substance": substance,
        "collected_at": collected_at,
        "accident_id": accident_id,
        "recorded_by_user_id": caller.user_id,
        "lab_result": "PENDING",
        "mro_verdict": "NONE",
        "verified_by_user_id": None,
        "verified_at": None,
        "status": "COLLECTED",
    })
    db["drug_alcohol_tests"][test["id"]] = test
    return success_object(public(test), 201)


@bp.get("/safety/drug-alcohol-tests")
def list_tests():
    return list_response("drug_alcohol_tests", filters={
        "driver_id": request.args.get("driver_id"),
        "test_type": request.args.get("test_type"),
        "status": request.args.get("status"),
        "accident_id": request.args.get("accident_id"),
    })


@bp.get("/safety/drug-alcohol-tests/<rid>")
def get_test(rid):
    return get_one("drug_alcohol_tests", rid)


@bp.post("/safety/drug-alcohol-tests/<rid>/report-lab-result")
def report_lab_result(rid):
    authorized(["SafetyManager"])
    body = get_body()
    lab_result = req_enum(body, "lab_result", LAB_RESULTS)
    test = require_path_resource("drug_alcohol_tests", rid)
    if test["status"] != "COLLECTED":
        raise_error(ERR_TEST_NOT_COLLECTED, "report-lab-result requires COLLECTED")
    test["lab_result"] = lab_result
    test["status"] = "CANCELLED" if lab_result == "CANCELLED_BY_LAB" else "LAB_REPORTED"
    touch(test)
    return success_object(public(test))


@bp.post("/safety/drug-alcohol-tests/<rid>/verify")
def verify(rid):
    caller = authorized(["MedicalReviewOfficer"])
    body = get_body()
    verdict = req_enum(body, "verdict", VERDICTS)
    test = require_path_resource("drug_alcohol_tests", rid)
    # Stage 5: state
    if test["status"] != "LAB_REPORTED":
        raise_error(ERR_TEST_NOT_LAB_REPORTED, "verify requires LAB_REPORTED")
    # Stage 7: segregation of duties
    if caller.user_id == test["recorded_by_user_id"]:
        raise_error(ERR_SOD_VERIFIER_IS_RECORDER,
                    "MRO verifier must differ from the test recorder")
    # Stage 9: verdict-to-result consistency (CANCELLED exempt)
    if verdict != "CANCELLED":
        expected = VERDICT_FOR_RESULT.get(test["lab_result"])
        if verdict != expected:
            raise_error(ERR_VERDICT_RESULT_MISMATCH,
                        f"verdict {verdict} inconsistent with lab_result {test['lab_result']}")
    test["mro_verdict"] = verdict
    test["verified_by_user_id"] = caller.user_id
    test["verified_at"] = fmt_datetime(CLOCK.now())
    test["status"] = "CANCELLED" if verdict == "CANCELLED" else "MRO_VERIFIED"
    touch(test)
    if verdict in ("VERIFIED_POSITIVE", "VERIFIED_REFUSAL"):
        driver = db["drivers"].get(test["driver_id"])
        if driver is not None and driver["employment_status"] == "ACTIVE":
            driver["employment_status"] = "SUSPENDED"
            touch(driver)
    return success_object(public(test))
