"""The reinspection revision loop.

Covers Difficulty queue: non_linear_state_machine (FAILED -> IN_PROGRESS cycle on a
fresh record). Covers Corner queue: validations (reinspection ceiling).
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
# Difficulty: non_linear_state_machine — FAILED -> IN_PROGRESS reinspection cycle
# ===========================================================================
def test_reinspect_failed_record_opens_fresh_in_progress_record(api):
    """PRD §3.9: "On a reinspection from a `FAILED` record, the failed record is
    marked superseded and its `version` is incremented, though it retains its
    `FAILED` status as chain history; a new `InspectionRecord` is created in
    `IN_PROGRESS` with `original_record_id` set to the head of the chain and
    `reinspection_index` set to one greater than the source's; and the supplied
    appointment is consumed, advancing it `CHECKED_IN → CONSUMED`."

    Design: Difficulty/non_linear_state_machine/inspection_record_failed_to_in_progress_reinspection_cycle
    """
    station, profile, lane = F.setup_station_with_passenger_obd(
        api, clock_iso="2026-06-10T09:00:00Z")
    appt1 = F.book_and_check_in(api, lane["id"],
                                scheduled_start="2026-06-10T09:00:00Z",
                                scheduled_end="2026-06-10T09:30:00Z")
    rec1 = F.open_record(api, appt1["id"])
    F.add_checklist(api, rec1["id"], item_code="BRAKES", outcome="FAIL", severity="CRITICAL")
    F.add_checklist(api, rec1["id"], item_code="LIGHTS", outcome="PASS")
    F.add_emissions(api, rec1["id"], mil_on=False, dtc_count=0)
    rec1 = F.decide_record(api, rec1["id"])
    assert rec1["status"] == "FAILED"

    appt2 = F.add_reinspection_appointment(
        api, lane["id"], "2026-06-10T10:00:00Z", "2026-06-10T10:30:00Z")
    rec2 = validate_success(
        api.reinspect_inspection_record(
            rec1["id"], {"reinspection_appointment_id": appt2["id"]}, INSP), 201)
    assert rec2["status"] == "IN_PROGRESS"
    assert rec2["reinspection_index"] == 1
    assert rec2["original_record_id"] == rec1["id"]
    # The source FAILED record stays FAILED as chain history.
    rec1_after = get_success_data(api.get_inspection_record(rec1["id"], SM))
    assert rec1_after["status"] == "FAILED"


def test_reinspected_failed_record_is_superseded_with_version_bump(api):
    """PRD §3.9: "On a reinspection from a `FAILED` record, the failed record is
    marked superseded and its `version` is incremented, though it retains its
    `FAILED` status as chain history"

    Design: Difficulty/non_linear_state_machine/inspection_record_failed_to_in_progress_reinspection_cycle
    """
    station, profile, lane = F.setup_station_with_passenger_obd(
        api, clock_iso="2026-06-10T09:00:00Z")
    appt1 = F.book_and_check_in(api, lane["id"],
                                scheduled_start="2026-06-10T09:00:00Z",
                                scheduled_end="2026-06-10T09:30:00Z")
    rec1 = F.open_record(api, appt1["id"])
    F.add_checklist(api, rec1["id"], item_code="BRAKES", outcome="FAIL", severity="CRITICAL")
    F.add_checklist(api, rec1["id"], item_code="LIGHTS", outcome="PASS")
    F.add_emissions(api, rec1["id"], mil_on=False, dtc_count=0)
    rec1 = F.decide_record(api, rec1["id"])
    version_before = rec1["version"]

    appt2 = F.add_reinspection_appointment(
        api, lane["id"], "2026-06-10T10:00:00Z", "2026-06-10T10:30:00Z")
    F.reinspect(api, rec1["id"], appt2["id"])

    rec1_after = get_success_data(api.get_inspection_record(rec1["id"], SM))
    assert rec1_after["status"] == "FAILED"
    assert rec1_after["version"] == version_before + 1, \
        "the superseded FAILED record's version must be incremented by the reinspect"


# ===========================================================================
# Corner: validations — reinspection limit (ceiling of 3)
# ===========================================================================
def test_fourth_reinspection_returns_reinspection_limit(api):
    """PRD §3.9: "A chain admits at most three reinspections: a reinspection is
    allowed only while the source's `reinspection_index` is less than 3, and an
    attempt once the chain has reached that ceiling is rejected with
    `ERR_REINSPECTION_LIMIT`."

    Design: Corner/validations/reinspection_limit_exceeded_returns_reinspection_limit
    """
    # Build a chain whose current FAILED record sits at reinspection_index == 3.
    station, profile, lane, records = F.setup_failed_then_reinspected_chain_at_index(
        api, target_index=3, clock_iso="2026-06-10T08:00:00Z")
    rec3 = records[3]
    assert rec3["reinspection_index"] == 3
    assert rec3["status"] == "FAILED"
    # A fourth reinspection (index already at the ceiling) must be refused.
    appt4 = F.add_reinspection_appointment(
        api, lane["id"], "2026-06-10T14:00:00Z", "2026-06-10T14:30:00Z")
    validate_error(
        api.reinspect_inspection_record(
            rec3["id"], {"reinspection_appointment_id": appt4["id"]}, INSP),
        ApiErrorId.ERR_REINSPECTION_LIMIT.value)
