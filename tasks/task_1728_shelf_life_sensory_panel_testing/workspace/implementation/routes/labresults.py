"""LabTestResult recording with endpoint-trip evaluation and the
failure-day cascade (PRD §3.6)."""
import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STUDY_STATE,
    ERR_MEASUREMENT_OUT_OF_RANGE, ERR_ARM_STUDY_MISMATCH,
    ERR_TIME_POINT_STUDY_MISMATCH,
)
from flask import Blueprint, request
from response import respond, respond_list
from services import (
    ser_lab_result, recompute_arm_failure, MEASURE_RANGES, TRIP_LIMITS,
    TEST_TYPES,
)
from util import body, paginate, req_enum, req_num, req_str, sort_created

bp = Blueprint("labresults", __name__)


def get_result(result_id):
    r = db.store["lab_results"].get(result_id)
    if r is None:
        raise_err(ERR_NOT_FOUND, f"LabTestResult {result_id} not found")
    return r


@bp.route("/lab-test-results", methods=["POST"])
@require_roles("LabAnalyst")
def create_result():
    b = body()
    study_id = req_str(b, "study_id")
    arm_id = req_str(b, "arm_id")
    time_point_id = req_str(b, "time_point_id")
    test_type = req_enum(b, "test_type", TEST_TYPES)
    measured_value = req_num(b, "measured_value")
    study = db.store["studies"].get(study_id)
    if study is None:
        raise_err(ERR_NOT_FOUND, f"Study {study_id} not found")
    arm = db.store["arms"].get(arm_id)
    if arm is None:
        raise_err(ERR_NOT_FOUND, f"StudyArm {arm_id} not found")
    tp = db.store["time_points"].get(time_point_id)
    if tp is None:
        raise_err(ERR_NOT_FOUND, f"SamplingTimePoint {time_point_id} "
                                 f"not found")
    if study["status"] not in ("IN_PROGRESS", "ANALYSIS", "REPORTING"):
        raise_err(ERR_INVALID_STUDY_STATE,
                  "lab results require the study to be IN_PROGRESS, "
                  "ANALYSIS or REPORTING")
    # Measurement-range check is evaluated BEFORE the referential checks
    # (PRD §3.6).
    lo, hi = MEASURE_RANGES[test_type]
    if measured_value < lo or measured_value > hi:
        raise_err(ERR_MEASUREMENT_OUT_OF_RANGE,
                  f"measured_value outside [{lo}, {hi}] for {test_type}")
    if arm["study_id"] != study_id:
        raise_err(ERR_ARM_STUDY_MISMATCH,
                  "arm_id does not belong to the study")
    if tp["study_id"] != study_id:
        raise_err(ERR_TIME_POINT_STUDY_MISMATCH,
                  "time_point_id does not belong to the study")
    # Endpoint limits are inclusive at-or-above thresholds.
    tripped = measured_value >= TRIP_LIMITS[test_type]
    result = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "study_id": study_id,
        "arm_id": arm_id,
        "time_point_id": time_point_id,
        "test_type": test_type,
        "measured_value": measured_value,
        "tripped": tripped,
        "created_at": clock.now(),
    }
    db.store["lab_results"][result["id"]] = result
    if tripped:
        recompute_arm_failure(arm)
    return respond(ser_lab_result(result), 201)


@bp.route("/lab-test-results", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_results():
    items = sort_created(db.store["lab_results"].values())
    for field in ("study_id", "arm_id", "time_point_id", "test_type"):
        v = request.args.get(field)
        if v is not None:
            items = [r for r in items if r[field] == v]
    page, pagination = paginate(items)
    return respond_list([ser_lab_result(r) for r in page], pagination)


@bp.route("/lab-test-results/<result_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_result(result_id):
    return respond(ser_lab_result(get_result(result_id)), 200)
