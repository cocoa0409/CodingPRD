"""Monitoring systems, the QA axis, and daily calibrations (PRD 3.2)."""

from flask import Blueprint

from constants import (
    API_PREFIX,
    CALIBRATION_RESULTS,
    CAL_STATUSES,
    PARAMETERS,
    QA_ACTIONS,
    QA_STATUSES,
    ROLE_FACILITY_OPERATOR,
    ROLE_QA_ANALYST,
    SYSTEM_TYPES,
)
from db import base_record, db, public, public_list, sort_rows, touch
from errors import fail
from lookup import (
    calibrations_of_system,
    facility_of_monitoring_system,
    facility_of_unit,
    find,
    get,
    rata_tests_of_system,
    systems_of_unit,
)
from middleware import ANY_ROLE, authenticate, enforce_facility_scope
from response import array_response, object_response
from services import calc
from services.cascade import demote_system_out_of_control, run_links_two_to_four
from validation import (
    apply_pagination,
    body_dict,
    check_range,
    dt_field,
    enum_field,
    int_field,
    match_filters,
    num_field,
    pagination,
    query_filters,
    str_field,
)

bp = Blueprint("monitoring_systems", __name__)

DEFAULT_CAL_SPEC_PCT = 2.5


# ---------------------------------------------------------------------------
# install / read
# ---------------------------------------------------------------------------

@bp.route(API_PREFIX + "/units/<unit_id>/monitoring-systems", methods=["POST"])
def install_system(unit_id):
    caller = authenticate((ROLE_QA_ANALYST, ROLE_FACILITY_OPERATOR))
    body = body_dict()
    enforce_facility_scope(caller, facility_of_unit(find("unit", unit_id)))

    parameter = enum_field(body, "parameter", PARAMETERS, required=True)
    system_type = enum_field(body, "system_type", SYSTEM_TYPES, required=True)
    span_value = num_field(body, "span_value", required=True)
    spec_pct = num_field(body, "calibration_error_spec_pct")

    unit = get("unit", unit_id)

    # A unit holds one live system per parameter; retirement releases the slot.
    for existing in systems_of_unit(unit["id"]):
        if existing["parameter"] == parameter and existing["qa_status"] != "RETIRED":
            fail(
                "ERR_DUPLICATE_MONITORING_SYSTEM",
                "A live monitoring system already exists for this parameter.",
            )

    check_range("span_value", span_value, minimum=0, min_exclusive=True)
    check_range("calibration_error_spec_pct", spec_pct, minimum=0, min_exclusive=True, maximum=20)

    system = base_record()
    system.update(
        {
            "unit_id": unit["id"],
            "parameter": parameter,
            "system_type": system_type,
            "span_value": float(span_value),
            "calibration_error_spec_pct": (
                DEFAULT_CAL_SPEC_PCT if spec_pct is None else float(spec_pct)
            ),
            "qa_status": "RECERTIFICATION_PENDING",
            "cal_status": "CAL_EXPIRED",
            "consecutive_failed_calibrations": 0,
            "out_of_control_since_utc": None,
            "last_calibration_utc": None,
            "bias_adjustment_factor": 1.0,
            "_out_of_control_since": None,
            "_last_calibration": None,
        }
    )
    db.monitoring_systems[system["id"]] = system
    return object_response(public(system), 201)


@bp.route(API_PREFIX + "/monitoring-systems", methods=["GET"])
def list_systems():
    authenticate(ANY_ROLE)
    filters = query_filters(
        {
            "unit_id": "str",
            "parameter": PARAMETERS,
            "system_type": SYSTEM_TYPES,
            "qa_status": QA_STATUSES,
            "cal_status": CAL_STATUSES,
        }
    )
    limit, offset = pagination()
    rows = match_filters(list(db.monitoring_systems.values()), filters)
    rows = sort_rows(rows)
    return array_response(
        public_list(apply_pagination(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.route(API_PREFIX + "/monitoring-systems/<system_id>", methods=["GET"])
def read_system(system_id):
    authenticate(ANY_ROLE)
    system = get("monitoring_system", system_id)
    return object_response(public(system))


# ---------------------------------------------------------------------------
# the QA axis
# ---------------------------------------------------------------------------

def _best_passed_bias_factor(system_id):
    """The passed audit with the greatest window_end_utc, ties by earlier
    created_at.
    """
    passed = [r for r in rata_tests_of_system(system_id) if r["status"] == "PASSED"]
    if not passed:
        return None
    passed.sort(key=lambda r: (r["created_at"], r["_seq"]))
    best = None
    for row in passed:
        if best is None or row["_window_end"] > best["_window_end"]:
            best = row
    return best["bias_adjustment_factor"]


@bp.route(API_PREFIX + "/monitoring-systems/<system_id>/qa-status", methods=["POST"])
def transition_qa_status(system_id):
    authenticate((ROLE_QA_ANALYST,))
    body = body_dict()

    action = enum_field(body, "action", QA_ACTIONS, required=True)
    effective_raw, effective = dt_field(body, "effective_utc")
    str_field(body, "reason")

    system = get("monitoring_system", system_id)
    current = system["qa_status"]

    if action == "CONDITIONALLY_VALIDATE":
        if current != "RECERTIFICATION_PENDING":
            fail("ERR_INVALID_STATE_TRANSITION", "CONDITIONALLY_VALIDATE requires RECERTIFICATION_PENDING.")
        system["qa_status"] = "CONDITIONALLY_VALID"
        touch(system)

    elif action == "CERTIFY":
        if current not in ("RECERTIFICATION_PENDING", "CONDITIONALLY_VALID", "OUT_OF_CONTROL"):
            fail("ERR_INVALID_STATE_TRANSITION", "CERTIFY is not permitted from %s." % current)
        # ERR_MONITOR_NOT_CERTIFIED precedes ERR_CALIBRATION_NOT_CURRENT (2.8).
        if any(r["status"] == "FAILED" for r in rata_tests_of_system(system["id"])):
            fail("ERR_MONITOR_NOT_CERTIFIED", "A relative accuracy audit of this system is FAILED.")
        if current == "OUT_OF_CONTROL":
            if system["cal_status"] != "CAL_CURRENT":
                fail("ERR_CALIBRATION_NOT_CURRENT", "Restoring from OUT_OF_CONTROL requires CAL_CURRENT.")
        else:
            if system["cal_status"] == "CAL_FAILED":
                fail("ERR_CALIBRATION_NOT_CURRENT", "cal_status must not be CAL_FAILED.")
        system["qa_status"] = "CERTIFIED"
        system["out_of_control_since_utc"] = None
        system["_out_of_control_since"] = None
        if current == "OUT_OF_CONTROL":
            system["consecutive_failed_calibrations"] = 0
        adopted = _best_passed_bias_factor(system["id"])
        if adopted is not None:
            system["bias_adjustment_factor"] = adopted
        touch(system)

    elif action == "DECLARE_OUT_OF_CONTROL":
        if current not in ("CERTIFIED", "CONDITIONALLY_VALID"):
            fail(
                "ERR_INVALID_STATE_TRANSITION",
                "DECLARE_OUT_OF_CONTROL is not permitted from %s." % current,
            )
        anchor_raw = effective_raw if effective_raw is not None else db.now_str()
        anchor = effective if effective is not None else db.now()
        demote_system_out_of_control(system, anchor_raw, anchor, fail_calibration=False)
        run_links_two_to_four(system, anchor)

    else:  # RETIRE
        if current != "CERTIFIED":
            fail("ERR_INVALID_STATE_TRANSITION", "A system is retired only out of CERTIFIED.")
        system["qa_status"] = "RETIRED"
        touch(system)

    return object_response(public(system))


# ---------------------------------------------------------------------------
# daily calibrations
# ---------------------------------------------------------------------------

@bp.route(API_PREFIX + "/monitoring-systems/<system_id>/daily-calibrations", methods=["POST"])
def record_calibration(system_id):
    caller = authenticate((ROLE_FACILITY_OPERATOR, ROLE_QA_ANALYST))
    body = body_dict()
    enforce_facility_scope(caller, facility_of_monitoring_system(find("monitoring_system", system_id)))

    expected_version = int_field(body, "expected_monitoring_system_version", required=True)
    calibration_raw, calibration_utc = dt_field(body, "calibration_utc", required=True)
    zero_reference = num_field(body, "zero_reference_value", required=True)
    zero_measured = num_field(body, "zero_measured_value", required=True)
    span_reference = num_field(body, "span_reference_value", required=True)
    span_measured = num_field(body, "span_measured_value", required=True)

    system = get("monitoring_system", system_id)

    # Version guard first of the state band (2.7 / 2.8 step 11).
    if expected_version != system["version"]:
        fail(
            "ERR_STALE_MONITORING_SYSTEM_VERSION",
            "expected_monitoring_system_version does not match the stored version.",
        )

    if system["qa_status"] == "RETIRED":
        fail("ERR_INVALID_STATE_TRANSITION", "A retired system accepts no calibrations.")

    for existing in calibrations_of_system(system["id"]):
        if existing["_calibration_utc"] == calibration_utc:
            fail("ERR_INVALID_REQUEST", "calibration_utc is already recorded for this system.")

    zero_pct, span_pct = calc.calibration_percentages(
        zero_reference, zero_measured, span_reference, span_measured, system["span_value"]
    )
    prior_failures = system["consecutive_failed_calibrations"]
    result = calc.calibration_verdict(
        zero_pct, span_pct, system["calibration_error_spec_pct"], prior_failures
    )

    # --- the calibration axis moves ---------------------------------------
    if result == "PASSED":
        system["cal_status"] = "CAL_CURRENT"
        system["consecutive_failed_calibrations"] = 0
    else:
        system["cal_status"] = "CAL_FAILED"
        system["consecutive_failed_calibrations"] = prior_failures + 1
    system["last_calibration_utc"] = calibration_raw
    system["_last_calibration"] = calibration_utc
    touch(system)

    # --- the out-of-control cascade ---------------------------------------
    if result == "OUT_OF_CONTROL_TRIGGERED" and system["qa_status"] in (
        "CERTIFIED",
        "CONDITIONALLY_VALID",
    ):
        demote_system_out_of_control(system, calibration_raw, calibration_utc)
        run_links_two_to_four(system, calibration_utc)

    calibration = base_record(versioned=False)
    calibration.update(
        {
            "monitoring_system_id": system["id"],
            "calibration_utc": calibration_raw,
            "zero_reference_value": float(zero_reference),
            "zero_measured_value": float(zero_measured),
            "span_reference_value": float(span_reference),
            "span_measured_value": float(span_measured),
            "zero_error_pct_of_span": zero_pct,
            "span_error_pct_of_span": span_pct,
            "result": result,
            "monitoring_system_version_after": system["version"],
            "_calibration_utc": calibration_utc,
        }
    )
    db.daily_calibrations[calibration["id"]] = calibration
    return object_response(public(calibration), 201)


@bp.route(API_PREFIX + "/monitoring-systems/<system_id>/daily-calibrations", methods=["GET"])
def list_system_calibrations(system_id):
    authenticate(ANY_ROLE)
    filters = query_filters({"result": CALIBRATION_RESULTS})
    limit, offset = pagination()
    system = get("monitoring_system", system_id)
    rows = match_filters(calibrations_of_system(system["id"]), filters)
    # A single system's calibration history reads newest first (2.3).
    rows = sort_rows(rows, descending=True)
    return array_response(
        public_list(apply_pagination(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.route(API_PREFIX + "/daily-calibrations", methods=["GET"])
def list_calibrations():
    authenticate(ANY_ROLE)
    filters = query_filters({"monitoring_system_id": "str", "result": CALIBRATION_RESULTS})
    limit, offset = pagination()
    rows = match_filters(list(db.daily_calibrations.values()), filters)
    rows = sort_rows(rows)
    return array_response(
        public_list(apply_pagination(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.route(API_PREFIX + "/daily-calibrations/<calibration_id>", methods=["GET"])
def read_calibration(calibration_id):
    authenticate(ANY_ROLE)
    calibration = get("daily_calibration", calibration_id)
    return object_response(public(calibration))
