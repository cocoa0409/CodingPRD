"""Opening and conducting an inspection: state guards, OBD verdict, the decision.

Covers Corner queue: state_machines (check-in/abort/open guards), calculations
(OBD verdict thresholds), validations (OBD-not-applicable, incomplete), and
consistency_model (decide returns frozen fee immediately).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    get_success_data, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as F

SM = TEST_USERS["station_manager_headers"]
INSP = TEST_USERS["inspector_headers"]
RECEP = TEST_USERS["receptionist_headers"]


# ===========================================================================
# Corner: state_machines — open record from BOOKED (not CHECKED_IN) rejected
# ===========================================================================
def test_open_record_from_booked_not_checked_in_returns_invalid_state(api):
    """PRD §3.4: "The appointment must be in `CHECKED_IN`, and no inspection record
    that is not `ABORTED` may already reference that `appointment_id`; otherwise the
    open is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/open_record_from_booked_not_checked_in_returns_invalid_state
    """
    station, profile, lane = F.setup_station_with_passenger_obd(api, clock_iso=None)
    appt = F.book_appointment(api, lane["id"])  # BOOKED, not checked in
    validate_error(
        api.create_inspection_record(F.create_inspection_record_payload(appt["id"]), INSP),
        ApiErrorId.ERR_INVALID_STATE.value)


def test_check_in_already_checked_in_appointment_returns_invalid_state(api):
    """PRD §3.2: "Any of these transitions attempted from a state other than
    `BOOKED` is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/check_in_already_checked_in_appointment_returns_invalid_state
    """
    station, profile, lane = F.setup_station_with_passenger_obd(api, clock_iso=None)
    appt = F.book_and_check_in(api, lane["id"])  # already CHECKED_IN
    validate_error(api.check_in_appointment(appt["id"], RECEP),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_abort_terminal_aborted_record_returns_invalid_state(api):
    """PRD §3.5: "A `StationManager` may instead abort an in-progress record,
    transitioning `IN_PROGRESS → ABORTED` and bumping its `version`. `ABORTED` is
    terminal and certifies nothing."
    PRD §2.9: "State legality is fifth: attempting a transition from a state in which
    it is not defined yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/abort_terminal_aborted_record_returns_invalid_state
    """
    station, profile, lane = F.setup_station_with_passenger_obd(api, clock_iso=None)
    appt = F.book_and_check_in(api, lane["id"])
    record = F.open_record(api, appt["id"])
    get_success_data(api.abort_inspection_record(record["id"], SM))  # now ABORTED
    validate_error(api.abort_inspection_record(record["id"], SM),
                   ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner: calculations — OBD verdict thresholds
# ===========================================================================
def test_obd_result_fail_when_mil_on(api):
    """PRD §3.4: "if `mil_on` is true the `result` is `FAIL`; otherwise if
    `dtc_count` is greater than zero (any stored trouble code) the `result` is
    `FAIL`; otherwise if `readiness_monitors_incomplete` is two or more — that is,
    more than the single incomplete monitor that is tolerated — the `result` is
    `FAIL`; otherwise the `result` is `PASS`."

    Design: Corner/calculations/obd_result_fail_when_mil_on
    """
    station, profile, lane, appt, record = F.setup_in_progress_passenger_record(api, clock_iso=None)
    test = get_success_data(api.create_emissions_test(F.create_emissions_test_payload(
        record["id"], protocol="OBD2_CAN", dtc_count=0,
        readiness_monitors_incomplete=0, mil_on=True), INSP))
    assert test["result"] == "FAIL", f"mil_on=True must yield FAIL, got {test['result']}"


def test_obd_result_fail_at_two_incomplete_monitors(api):
    """PRD §3.4: "otherwise if `readiness_monitors_incomplete` is two or more — that
    is, more than the single incomplete monitor that is tolerated — the `result` is
    `FAIL`; otherwise the `result` is `PASS`."

    Design: Corner/calculations/obd_result_fail_at_two_incomplete_monitors_boundary
    """
    station, profile, lane, appt, record = F.setup_in_progress_passenger_record(api, clock_iso=None)
    test = get_success_data(api.create_emissions_test(F.create_emissions_test_payload(
        record["id"], protocol="OBD2_ISO", dtc_count=0,
        readiness_monitors_incomplete=2, mil_on=False), INSP))
    assert test["result"] == "FAIL", \
        f"readiness_monitors_incomplete=2 (>1) must yield FAIL, got {test['result']}"


def test_obd_result_pass_at_one_incomplete_monitor(api):
    """PRD §3.4: "In short, a pass requires the lamp off, zero stored codes, and at
    most one incomplete readiness monitor."

    Design: Corner/calculations/obd_result_pass_at_one_incomplete_monitor_boundary
    """
    station, profile, lane, appt, record = F.setup_in_progress_passenger_record(api, clock_iso=None)
    test = get_success_data(api.create_emissions_test(F.create_emissions_test_payload(
        record["id"], protocol="OBD2_J1850", dtc_count=0,
        readiness_monitors_incomplete=1, mil_on=False), INSP))
    assert test["result"] == "PASS", \
        f"readiness_monitors_incomplete=1 (==tolerated max) must PASS, got {test['result']}"


# ===========================================================================
# Corner: validations — emissions test on non-OBD class
# ===========================================================================
def test_emissions_test_on_non_obd_class_returns_obd_not_applicable(api):
    """PRD §3.4: "An emissions test may be attached only when the record's class
    profile has `obd_required` true, and at most one test may exist per record; an
    attempt to attach a test to a non-OBD class, or to attach a second test, is
    rejected with `ERR_OBD_NOT_APPLICABLE`."

    Design: Corner/validations/emissions_test_on_non_obd_class_returns_obd_not_applicable
    """
    station, profile, lane = F.setup_station_with_motorcycle_no_obd(api, clock_iso=None)
    appt = F.book_and_check_in(api, lane["id"], vehicle_vin="JH2SC82A4MM100001",
                               vehicle_class="MOTORCYCLE",
                               scheduled_end="2026-06-10T09:20:00Z")
    record = F.open_record(api, appt["id"])
    validate_error(
        api.create_emissions_test(F.create_emissions_test_payload(record["id"]), INSP),
        ApiErrorId.ERR_OBD_NOT_APPLICABLE.value)


# ===========================================================================
# Corner: validations — decide with missing checklist items
# ===========================================================================
def test_decide_with_missing_checklist_items_returns_inspection_incomplete(api):
    """PRD §3.5: "Before any outcome can be computed, the inspection must be
    complete: the number of `ChecklistResult` rows for the record must equal the
    class profile's `checklist_item_count`, and when the class requires OBD exactly
    one `EmissionsTest` must exist. If items are missing, or the required emissions
    test is absent, the decision is rejected with `ERR_INSPECTION_INCOMPLETE`."

    Design: Corner/validations/decide_with_missing_checklist_items_returns_inspection_incomplete
    """
    station, profile, lane, appt, record = F.setup_in_progress_passenger_record(api, clock_iso=None)
    F.add_checklist(api, record["id"], item_code="BRAKES", outcome="PASS")  # only 1 of 2
    F.add_emissions(api, record["id"], mil_on=False, dtc_count=0)
    validate_error(api.decide_inspection_record(record["id"], INSP),
                   ApiErrorId.ERR_INSPECTION_INCOMPLETE.value)


# ===========================================================================
# Corner: consistency_model — decide returns frozen fee in same response
# ===========================================================================
def test_decide_returns_frozen_fee_and_status_in_same_response(api):
    """PRD §3.6: "To the base it adds an emissions surcharge: when the class requires
    OBD the surcharge is ten dollars (1000 cents), and when it does not the surcharge
    is zero."
    PRD §3.6: "A flat state environmental fee of two dollars (200 cents) is always
    added afterward regardless of relief."
    PRD §3.5: "When every one of these is satisfied the record transitions
    `IN_PROGRESS → PASSED`."

    Design: Corner/consistency_model/decide_returns_frozen_fee_in_same_response
    """
    station, profile, lane, appt, record = F.setup_in_progress_passenger_record(api, clock_iso=None)
    F.add_checklist(api, record["id"], item_code="BRAKES", outcome="PASS")
    F.add_checklist(api, record["id"], item_code="LIGHTS", outcome="PASS")
    F.add_emissions(api, record["id"], mil_on=False, dtc_count=0)
    decided = validate_success(api.decide_inspection_record(record["id"], INSP), 200)
    assert decided["status"] == "PASSED"
    assert decided["fee_cents"] == 3700, \
        f"PASSENGER+OBD first inspection fee must be 3700 (2500+1000+200), got {decided['fee_cents']}"
