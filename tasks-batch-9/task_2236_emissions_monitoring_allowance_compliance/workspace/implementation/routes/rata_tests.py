"""Relative accuracy test audits: scheduling, runs, evaluation and the retest
cycle on a single row (PRD 3.3).
"""

from flask import Blueprint

from constants import (
    API_PREFIX,
    LOW_EMITTER_THRESHOLD,
    RATA_MAX_RUNS,
    RATA_MIN_RUNS,
    RATA_STATUSES,
    RA_BASES,
    ROLE_QA_ANALYST,
)
from db import base_record, db, public, public_list, sort_rows, touch
from errors import fail
from lookup import get, rata_tests_of_system, require_child_of
from middleware import ANY_ROLE, authenticate
from response import array_response, object_response
from services import calc
from validation import (
    apply_pagination,
    body_dict,
    check_range,
    dt_field,
    enum_field,
    id_field,
    list_field,
    match_filters,
    num_field,
    pagination,
    query_filters,
)
from util import D

bp = Blueprint("rata_tests", __name__)


def _validate_window(system_id, start, end, exclude_id=None):
    """The three window rules, in ladder order: interval, overlap, past."""
    if start >= end:
        fail("ERR_INVALID_INTERVAL", "window_end_utc must be strictly later than window_start_utc.")
    for other in rata_tests_of_system(system_id):
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["status"] not in ("SCHEDULED", "RUNS_RECORDED"):
            continue
        # half-open comparison: abutting windows are accepted
        if start < other["_window_end"] and other["_window_start"] < end:
            fail("ERR_RATA_WINDOW_OVERLAP", "The window overlaps another live audit of this system.")
    if start < db.now():
        fail("ERR_RATA_WINDOW_IN_PAST", "window_start_utc is before the logical clock.")


@bp.route(API_PREFIX + "/monitoring-systems/<system_id>/rata-tests", methods=["POST"])
def schedule_rata(system_id):
    authenticate((ROLE_QA_ANALYST,))
    body = body_dict()

    start_raw, start = dt_field(body, "window_start_utc", required=True)
    end_raw, end = dt_field(body, "window_end_utc", required=True)
    standard = num_field(body, "applicable_standard_value")
    predecessor_id = id_field(body, "retest_of_rata_test_id")

    system = get("monitoring_system", system_id)

    predecessor = None
    if predecessor_id is not None:
        predecessor = get("rata_test", predecessor_id)
        require_child_of("rata_test", predecessor, "monitoring_system_id", system["id"])
        if predecessor["status"] != "FAILED":
            fail("ERR_RETEST_ALREADY_EXISTS", "The named predecessor is not sitting in FAILED.")
        for other in db.rata_tests.values():
            if other.get("retest_of_rata_test_id") == predecessor["id"]:
                fail("ERR_RETEST_ALREADY_EXISTS", "The named predecessor is already retested.")

    _validate_window(system["id"], start, end)
    check_range("applicable_standard_value", standard, minimum=0, min_exclusive=True)

    attempt_number = 1
    if predecessor is not None:
        attempt_number = predecessor["attempt_number"] + 1
        predecessor["status"] = "VOIDED"
        touch(predecessor)

    audit = base_record()
    audit.update(
        {
            "monitoring_system_id": system["id"],
            "retest_of_rata_test_id": predecessor["id"] if predecessor else None,
            "window_start_utc": start_raw,
            "window_end_utc": end_raw,
            "applicable_standard_value": None if standard is None else float(standard),
            "status": "SCHEDULED",
            "runs": [],
            "run_count": 0,
            "reference_mean": None,
            "cems_mean": None,
            "mean_difference": None,
            "confidence_coefficient": None,
            "ra_basis": "REFERENCE_MEAN",
            "relative_accuracy_pct": None,
            "bias_test_failed": False,
            "bias_adjustment_factor": 1.0,
            "attempt_number": attempt_number,
            "_window_start": start,
            "_window_end": end,
        }
    )
    db.rata_tests[audit["id"]] = audit
    return object_response(public(audit), 201)


@bp.route(API_PREFIX + "/rata-tests", methods=["GET"])
def list_rata_tests():
    authenticate(ANY_ROLE)
    filters = query_filters(
        {
            "monitoring_system_id": "str",
            "retest_of_rata_test_id": "str",
            "status": RATA_STATUSES,
            "ra_basis": RA_BASES,
        }
    )
    limit, offset = pagination()
    rows = match_filters(list(db.rata_tests.values()), filters)
    rows = sort_rows(rows)
    return array_response(
        public_list(apply_pagination(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.route(API_PREFIX + "/rata-tests/<rata_id>", methods=["GET"])
def read_rata_test(rata_id):
    authenticate(ANY_ROLE)
    return object_response(public(get("rata_test", rata_id)))


@bp.route(API_PREFIX + "/rata-tests/<rata_id>/runs", methods=["POST"])
def record_runs(rata_id):
    authenticate((ROLE_QA_ANALYST,))
    body = body_dict()

    runs = list_field(body, "runs", required=True)
    parsed = []
    for item in runs:
        if not isinstance(item, dict):
            fail("ERR_INVALID_REQUEST", "Each run must be an object.")
        reference = num_field(item, "reference_value", required=True)
        cems = num_field(item, "cems_value", required=True)
        parsed.append({"reference_value": float(reference), "cems_value": float(cems)})

    audit = get("rata_test", rata_id)
    system = get("monitoring_system", audit["monitoring_system_id"])

    if audit["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE_TRANSITION", "Runs may only be recorded on a SCHEDULED audit.")
    if system["qa_status"] == "RETIRED":
        fail("ERR_INVALID_STATE_TRANSITION", "The audited system is retired.")

    unit = db.units.get(system["unit_id"])
    if unit is None or unit["dispatch_state"] != "ONLINE":
        fail("ERR_UNIT_NOT_ONLINE", "The audited unit must be dispatching ONLINE.")

    if len(parsed) < RATA_MIN_RUNS or len(parsed) > RATA_MAX_RUNS:
        fail("ERR_INSUFFICIENT_RATA_RUNS", "runs must hold between 9 and 12 pairs.")
    for item in parsed:
        if D(item["reference_value"]) <= 0 or D(item["cems_value"]) <= 0:
            fail("ERR_INSUFFICIENT_RATA_RUNS", "Every run value must be positive.")

    stats = calc.rata_statistics(parsed)
    audit["runs"] = parsed
    audit["run_count"] = len(parsed)
    audit["reference_mean"] = stats["reference_mean"]
    audit["cems_mean"] = stats["cems_mean"]
    audit["mean_difference"] = stats["mean_difference"]
    audit["confidence_coefficient"] = stats["confidence_coefficient"]
    audit["status"] = "RUNS_RECORDED"
    touch(audit)
    return object_response(public(audit))


@bp.route(API_PREFIX + "/rata-tests/<rata_id>/evaluate", methods=["POST"])
def evaluate_rata(rata_id):
    authenticate((ROLE_QA_ANALYST,))
    body = body_dict()
    ra_basis = enum_field(body, "ra_basis", RA_BASES, required=True)

    audit = get("rata_test", rata_id)
    system = get("monitoring_system", audit["monitoring_system_id"])

    if audit["status"] != "RUNS_RECORDED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a RUNS_RECORDED audit may be evaluated.")

    if ra_basis == "APPLICABLE_STANDARD":
        threshold = LOW_EMITTER_THRESHOLD[system["parameter"]]
        if audit["applicable_standard_value"] is None:
            fail("ERR_RA_BASIS_NOT_PERMITTED", "applicable_standard_value is absent.")
        if D(audit["reference_mean"]) > threshold:
            fail("ERR_RA_BASIS_NOT_PERMITTED", "The source is not a low emitter for this parameter.")
        denominator = audit["applicable_standard_value"]
    else:
        denominator = audit["reference_mean"]

    accuracy = calc.relative_accuracy(
        audit["mean_difference"], audit["confidence_coefficient"], denominator
    )
    passed = calc.rata_passed(accuracy)
    bias_failed = abs(D(audit["mean_difference"])) > abs(D(audit["confidence_coefficient"]))
    factor = (
        calc.bias_adjustment(audit["mean_difference"], audit["cems_mean"])
        if bias_failed
        else 1.0
    )

    audit["ra_basis"] = ra_basis
    audit["relative_accuracy_pct"] = accuracy
    audit["bias_test_failed"] = bias_failed
    audit["bias_adjustment_factor"] = factor
    audit["status"] = "PASSED" if passed else "FAILED"
    touch(audit)

    # propagation onto the monitoring system
    if passed and system["qa_status"] == "CERTIFIED":
        system["bias_adjustment_factor"] = factor
        touch(system)
    elif not passed and system["qa_status"] == "CERTIFIED":
        system["qa_status"] = "CONDITIONALLY_VALID"
        touch(system)

    return object_response(public(audit))


@bp.route(API_PREFIX + "/rata-tests/<rata_id>/reschedule", methods=["POST"])
def reschedule_rata(rata_id):
    authenticate((ROLE_QA_ANALYST,))
    body = body_dict()

    start_raw, start = dt_field(body, "window_start_utc", required=True)
    end_raw, end = dt_field(body, "window_end_utc", required=True)

    audit = get("rata_test", rata_id)
    if audit["status"] != "FAILED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a FAILED audit may be rescheduled.")

    _validate_window(audit["monitoring_system_id"], start, end, exclude_id=audit["id"])

    audit["window_start_utc"] = start_raw
    audit["window_end_utc"] = end_raw
    audit["_window_start"] = start
    audit["_window_end"] = end
    audit["runs"] = []
    audit["run_count"] = 0
    audit["reference_mean"] = None
    audit["cems_mean"] = None
    audit["mean_difference"] = None
    audit["confidence_coefficient"] = None
    audit["relative_accuracy_pct"] = None
    audit["bias_test_failed"] = False
    audit["bias_adjustment_factor"] = 1.0
    audit["ra_basis"] = "REFERENCE_MEAN"
    audit["attempt_number"] = audit["attempt_number"] + 1
    audit["status"] = "SCHEDULED"
    touch(audit)
    return object_response(public(audit))
