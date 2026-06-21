"""Lane scheduling and shared-analyzer concurrency — the two interval disciplines.

Covers Difficulty queue rule resource_temporal_overlap (lane buffer-adjacency and
analyzer aggregate capacity), plus Corner queue scheduling claims (time range,
adjacency-succeeds, touching-succeeds, cancel-releases-slot, no-show precondition).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    get_success_data, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as F

SM = TEST_USERS["station_manager_headers"]
RECEP = TEST_USERS["receptionist_headers"]


# ===========================================================================
# Difficulty: resource_temporal_overlap — lane single-occupant buffer adjacency
# ===========================================================================
def test_lane_buffer_extends_slot_tail_causing_conflict(api):
    """PRD §3.2: "to it the system appends the lane's `turnaround_buffer_minutes` of
    clean-down. The booking is rejected with `ERR_LANE_TIME_CONFLICT` if this
    buffered span overlaps the buffered span of any appointment on the same lane that
    has not been released — that is, any appointment still in `BOOKED`,
    `CHECKED_IN`, or `CONSUMED`."

    Design: Difficulty/resource_temporal_overlap/lane_appointment_buffer_adjacency_overlap
    """
    station, profile, lane = F.setup_station_with_passenger_obd(
        api, clock_iso="2026-06-10T08:00:00Z", buffer_minutes=15)
    F.book_appointment(api, lane["id"], kind="APPOINTMENT",
                       scheduled_start="2026-06-10T09:00:00Z",
                       scheduled_end="2026-06-10T09:30:00Z")
    # Existing slot occupies [09:00, 09:45) with the 15-min buffer; [09:30,10:00) overlaps.
    resp = api.create_appointment(F.create_appointment_payload(
        lane["id"], vehicle_vin="2HGCM82633A004353", kind="APPOINTMENT",
        scheduled_start="2026-06-10T09:30:00Z", scheduled_end="2026-06-10T10:00:00Z"), RECEP)
    validate_error(resp, ApiErrorId.ERR_LANE_TIME_CONFLICT.value)


def test_lane_adjacency_at_existing_end_plus_buffer_succeeds(api):
    """PRD §3.2: "The intervals are half-open, so exact adjacency at the boundary,
    where the new slot starts precisely at an existing appointment's end plus its
    buffer, does not conflict."

    Design: Difficulty/resource_temporal_overlap/lane_appointment_buffer_adjacency_overlap
    """
    station, profile, lane = F.setup_station_with_passenger_obd(
        api, clock_iso="2026-06-10T08:00:00Z", buffer_minutes=15)
    F.book_appointment(api, lane["id"], kind="APPOINTMENT",
                       scheduled_start="2026-06-10T09:00:00Z",
                       scheduled_end="2026-06-10T09:30:00Z")
    # Existing end 09:30 + 15-min buffer = 09:45; new slot starting exactly at 09:45 is fine.
    resp = api.create_appointment(F.create_appointment_payload(
        lane["id"], vehicle_vin="2HGCM82633A004353", kind="APPOINTMENT",
        scheduled_start="2026-06-10T09:45:00Z", scheduled_end="2026-06-10T10:15:00Z"), RECEP)
    data = validate_success(resp, 201)
    assert data["status"] == "BOOKED"


# ===========================================================================
# Corner: validations — half-open lane adjacency exactly at buffer end succeeds
# ===========================================================================
def test_lane_appointment_adjacency_exactly_at_buffer_end_succeeds(api):
    """PRD §3.2: "The intervals are half-open, so exact adjacency at the boundary,
    where the new slot starts precisely at an existing appointment's end plus its
    buffer, does not conflict."

    Design: Corner/validations/lane_appointment_adjacency_exactly_at_buffer_end_succeeds
    """
    station, profile, lane = F.setup_station_with_passenger_obd(
        api, clock_iso=None, buffer_minutes=15)
    F.book_appointment(api, lane["id"], kind="APPOINTMENT",
                       scheduled_start="2026-06-10T09:00:00Z",
                       scheduled_end="2026-06-10T09:30:00Z")
    resp = api.create_appointment(F.create_appointment_payload(
        lane["id"], vehicle_vin="2HGCM82633A004353", kind="APPOINTMENT",
        scheduled_start="2026-06-10T09:45:00Z", scheduled_end="2026-06-10T10:15:00Z"), RECEP)
    data = validate_success(resp, 201)
    assert data["status"] == "BOOKED"


# ===========================================================================
# Difficulty: resource_temporal_overlap — analyzer aggregate capacity
# ===========================================================================
def test_analyzer_second_overlapping_window_exceeds_capacity(api):
    """PRD §3.3: "if admitting it would bring the count of strictly-overlapping held
    windows to the station's `analyzer_count` or beyond, it is rejected with
    `ERR_ANALYZER_CAPACITY`."

    Design: Difficulty/resource_temporal_overlap/analyzer_aggregate_capacity_overlap
    """
    station = F.create_station(api, analyzer_count=1)
    get_success_data(api.create_analyzer_reservation({
        "station_id": station["id"], "vehicle_vin": "1HGCM82633A004352",
        "window_start": "2026-06-10T10:00:00Z", "window_end": "2026-06-10T11:00:00Z"}, RECEP))
    # [10:30,11:30) strictly overlaps [10:00,11:00); concurrency would be 2 > 1.
    resp = api.create_analyzer_reservation({
        "station_id": station["id"], "vehicle_vin": "2HGCM82633A004353",
        "window_start": "2026-06-10T10:30:00Z", "window_end": "2026-06-10T11:30:00Z"}, RECEP)
    validate_error(resp, ApiErrorId.ERR_ANALYZER_CAPACITY.value)


def test_analyzer_touching_window_does_not_overlap(api):
    """PRD §3.3: "Two windows are in conflict only when their intervals strictly
    overlap — that is, when their intersection has positive length; windows that
    merely touch at an endpoint do not overlap."

    Design: Difficulty/resource_temporal_overlap/analyzer_aggregate_capacity_overlap
    """
    station = F.create_station(api, analyzer_count=1)
    get_success_data(api.create_analyzer_reservation({
        "station_id": station["id"], "vehicle_vin": "1HGCM82633A004352",
        "window_start": "2026-06-10T10:00:00Z", "window_end": "2026-06-10T11:00:00Z"}, RECEP))
    # [11:00,12:00) merely touches [10:00,11:00) at the endpoint; admitted.
    resp = api.create_analyzer_reservation({
        "station_id": station["id"], "vehicle_vin": "2HGCM82633A004353",
        "window_start": "2026-06-10T11:00:00Z", "window_end": "2026-06-10T12:00:00Z"}, RECEP)
    data = validate_success(resp, 201)
    assert data["status"] == "HELD"


# ===========================================================================
# Corner: validations — touching window at capacity one succeeds
# ===========================================================================
def test_analyzer_touching_window_at_capacity_one_succeeds(api):
    """PRD §3.3: "windows that merely touch at an endpoint do not overlap."

    Design: Corner/validations/analyzer_touching_window_at_capacity_one_succeeds
    """
    station = F.create_station(api, analyzer_count=1)
    get_success_data(api.create_analyzer_reservation({
        "station_id": station["id"], "vehicle_vin": "1HGCM82633A004352",
        "window_start": "2026-06-10T10:00:00Z", "window_end": "2026-06-10T11:00:00Z"}, RECEP))
    resp = api.create_analyzer_reservation({
        "station_id": station["id"], "vehicle_vin": "2HGCM82633A004353",
        "window_start": "2026-06-10T11:00:00Z", "window_end": "2026-06-10T12:00:00Z"}, RECEP)
    data = validate_success(resp, 201)
    assert data["status"] == "HELD"


# ===========================================================================
# Corner: validations — appointment invalid time range
# ===========================================================================
def test_appointment_end_not_after_start_returns_invalid_time_range(api):
    """PRD §3.2: "First, the slot must be a valid interval: `scheduled_end` must be
    strictly after `scheduled_start`, or the request is rejected with
    `ERR_INVALID_TIME_RANGE`."

    Design: Corner/validations/appointment_end_not_after_start_returns_invalid_time_range
    """
    station, profile, lane = F.setup_station_with_passenger_obd(api, clock_iso=None)
    resp = api.create_appointment(F.create_appointment_payload(
        lane["id"], scheduled_start="2026-06-10T09:00:00Z",
        scheduled_end="2026-06-10T09:00:00Z"), RECEP)
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE.value)


# ===========================================================================
# Corner: state_machines — cancel releases slot for reuse
# ===========================================================================
def test_cancel_appointment_releases_slot_allows_reuse(api):
    """PRD §3.2: "Cancelling it advances `BOOKED` to `CANCELLED`, releasing the
    reserved slot back to the lane and bumping its `version`."

    Design: Corner/state_machines/cancel_appointment_releases_slot_allows_reuse
    """
    station, profile, lane = F.setup_station_with_passenger_obd(api, clock_iso=None)
    appt1 = F.book_appointment(api, lane["id"], kind="APPOINTMENT",
                               scheduled_start="2026-06-10T09:00:00Z",
                               scheduled_end="2026-06-10T09:30:00Z")
    get_success_data(api.cancel_appointment(appt1["id"], RECEP))
    # Same window should now be free.
    resp = api.create_appointment(F.create_appointment_payload(
        lane["id"], vehicle_vin="2HGCM82633A004353", kind="APPOINTMENT",
        scheduled_start="2026-06-10T09:00:00Z", scheduled_end="2026-06-10T09:30:00Z"), RECEP)
    data = validate_success(resp, 201)
    assert data["status"] == "BOOKED"


# ===========================================================================
# Difficulty: cross_entity_state_dependency — appointment requires a class profile
# ===========================================================================
def test_book_appointment_without_matching_class_profile_returns_missing(api):
    """PRD §3.2: "Third, the declared `vehicle_class` must have a matching
    `VehicleClassProfile` at the lane's station; if no such profile exists the
    booking is rejected with `ERR_CLASS_PROFILE_MISSING`."

    Design: Difficulty/cross_entity_state_dependency/appointment_requires_vehicle_class_profile_at_lane_station
    """
    # Station has only a PASSENGER profile; booking a HEAVY_DUTY appointment has no match.
    station, profile, lane = F.setup_station_with_passenger_obd(
        api, clock_iso="2026-06-10T09:00:00Z")
    resp = api.create_appointment(F.create_appointment_payload(
        lane["id"], vehicle_vin="1FTFW1ET5DFC10312", vehicle_class="HEAVY_DUTY"), RECEP)
    validate_error(resp, ApiErrorId.ERR_CLASS_PROFILE_MISSING.value)


def test_book_appointment_with_matching_class_profile_succeeds(api):
    """PRD §3.2: "Third, the declared `vehicle_class` must have a matching
    `VehicleClassProfile` at the lane's station; if no such profile exists the
    booking is rejected with `ERR_CLASS_PROFILE_MISSING`. When all gates pass, the
    slot is reserved on the lane."

    Design: Difficulty/cross_entity_state_dependency/appointment_requires_vehicle_class_profile_at_lane_station
    """
    # The PASSENGER profile exists, so a PASSENGER appointment is admitted.
    station, profile, lane = F.setup_station_with_passenger_obd(
        api, clock_iso="2026-06-10T09:00:00Z")
    resp = api.create_appointment(F.create_appointment_payload(
        lane["id"], vehicle_class="PASSENGER"), RECEP)
    data = validate_success(resp, 201)
    assert data["status"] == "BOOKED"


# ===========================================================================
# Corner: state_machines — no-show before scheduled_end rejected
# ===========================================================================
def test_no_show_before_scheduled_end_returns_invalid_state(api):
    """PRD §3.2: "Marking it a no-show advances `BOOKED` to `NO_SHOW`, but only once
    the logical clock has reached or passed the appointment's `scheduled_end`; the
    no-show likewise releases the slot and bumps the `version`."

    Design: Corner/state_machines/no_show_before_scheduled_end_returns_invalid_state
    """
    station, profile, lane = F.setup_station_with_passenger_obd(
        api, clock_iso="2026-06-10T08:00:00Z")
    appt = F.book_appointment(api, lane["id"], kind="APPOINTMENT",
                              scheduled_start="2026-06-10T09:00:00Z",
                              scheduled_end="2026-06-10T09:30:00Z")
    F.set_clock(api, "2026-06-10T09:10:00Z")  # before scheduled_end 09:30
    validate_error(api.no_show_appointment(appt["id"], RECEP),
                   ApiErrorId.ERR_INVALID_STATE.value)
