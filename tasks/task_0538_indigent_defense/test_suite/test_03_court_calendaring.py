"""Court-event calendaring: attorney travel buffer, courtroom overlap,
referential/temporal precedence, past events, and vacate."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

CLERK = TEST_USERS["intake_clerk_headers"]
COORD = TEST_USERS["assignment_coordinator_headers"]


def _assigned_case(office, attorney, defendant):
    case = fx.create_case(office["id"], defendant_name=defendant)
    scr = fx.submit_screening(case["id"])
    fx.decide_screening(scr["id"])
    fx.create_conflict_check(case["id"], attorney["id"])
    fx.create_assignment(case["id"], attorney["id"])
    return case


def _screened_case(office, attorney, defendant):
    case = fx.create_case(office["id"], defendant_name=defendant)
    scr = fx.submit_screening(case["id"])
    fx.decide_screening(scr["id"])
    fx.create_conflict_check(case["id"], attorney["id"])
    return case


# ===========================================================================
# Difficulty: attorney travel buffer (30 min edge-to-edge)
# ===========================================================================

def test_attorney_event_within_travel_buffer_rejected(api):
    """PRD 3.5: "The assigned attorney's calendar is protected by a thirty-minute
    travel buffer: the new event must be at least thirty minutes edge-to-edge
    away from every other `SCHEDULED` event of that same attorney, treating the
    intervals as half-open and adding the buffer, and any encroachment is
    rejected with `ERR_ATTORNEY_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/attorney_calendar_travel_buffer
    """
    office = fx.create_office()
    attorney = fx.create_attorney(office["id"], name="Ova", bar_number="OO1")
    room1 = fx.create_courtroom(name="Room 1", courthouse="Main")
    room2 = fx.create_courtroom(name="Room 2", courthouse="Annex")
    c1 = _assigned_case(office, attorney, "A1")
    c2 = _assigned_case(office, attorney, "A2")
    validate_success(api.create_court_event(
        {"case_id": c1["id"], "courtroom_id": room1["id"], "event_type": "MOTION_HEARING",
         "scheduled_start": "2026-06-10T09:00:00Z", "scheduled_end": "2026-06-10T10:00:00Z"},
        COORD), 201)
    # 10:15 is only 15 min after prior end 10:00 (< 30 buffer). Different room isolates the attorney rule.
    resp = api.create_court_event(
        {"case_id": c2["id"], "courtroom_id": room2["id"], "event_type": "MOTION_HEARING",
         "scheduled_start": "2026-06-10T10:15:00Z", "scheduled_end": "2026-06-10T11:00:00Z"},
        COORD)
    validate_error(resp, ApiErrorId.ERR_ATTORNEY_SCHEDULE_CONFLICT.value)


def test_attorney_event_exactly_at_buffer_allowed(api):
    """PRD 3.5: "The assigned attorney's calendar is protected by a thirty-minute
    travel buffer: the new event must be at least thirty minutes edge-to-edge
    away from every other `SCHEDULED` event of that same attorney, treating the
    intervals as half-open and adding the buffer, and any encroachment is
    rejected with `ERR_ATTORNEY_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/attorney_calendar_travel_buffer
    """
    office = fx.create_office()
    attorney = fx.create_attorney(office["id"], name="Ovb", bar_number="OO2")
    room1 = fx.create_courtroom(name="Room 1", courthouse="Main")
    room2 = fx.create_courtroom(name="Room 2", courthouse="Annex")
    c1 = _assigned_case(office, attorney, "B1")
    c2 = _assigned_case(office, attorney, "B2")
    validate_success(api.create_court_event(
        {"case_id": c1["id"], "courtroom_id": room1["id"], "event_type": "MOTION_HEARING",
         "scheduled_start": "2026-06-10T09:00:00Z", "scheduled_end": "2026-06-10T10:00:00Z"},
        COORD), 201)
    # 10:30 is exactly 30 min after prior end 10:00 -> allowed.
    ev = validate_success(api.create_court_event(
        {"case_id": c2["id"], "courtroom_id": room2["id"], "event_type": "MOTION_HEARING",
         "scheduled_start": "2026-06-10T10:30:00Z", "scheduled_end": "2026-06-10T11:00:00Z"},
        COORD), 201)
    assert ev["status"] == "SCHEDULED"


# ===========================================================================
# Difficulty: courtroom overlap (no buffer, back-to-back allowed)
# ===========================================================================

def test_courtroom_overlapping_event_rejected(api):
    """PRD 3.5: "The courtroom's calendar is protected without a buffer: the new
    event must not overlap any other `SCHEDULED` event in the same courtroom,
    again treating intervals as half-open so that two events sharing an exact
    boundary sit back-to-back and are allowed; an overlap is rejected with
    `ERR_COURTROOM_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/courtroom_overlap_adjacency_allowed
    """
    office = fx.create_office()
    att_a = fx.create_attorney(office["id"], name="Oaa", bar_number="OA1")
    att_b = fx.create_attorney(office["id"], name="Obb", bar_number="OB1")
    room = fx.create_courtroom(name="Room 9", courthouse="Main")
    ca = _assigned_case(office, att_a, "Oa")
    cb = _assigned_case(office, att_b, "Ob")
    validate_success(api.create_court_event(
        {"case_id": ca["id"], "courtroom_id": room["id"], "event_type": "PRETRIAL",
         "scheduled_start": "2026-06-10T09:00:00Z", "scheduled_end": "2026-06-10T10:00:00Z"},
        COORD), 201)
    resp = api.create_court_event(
        {"case_id": cb["id"], "courtroom_id": room["id"], "event_type": "PRETRIAL",
         "scheduled_start": "2026-06-10T09:30:00Z", "scheduled_end": "2026-06-10T10:30:00Z"},
        COORD)
    validate_error(resp, ApiErrorId.ERR_COURTROOM_DOUBLE_BOOKED.value)


def test_courtroom_back_to_back_event_allowed(api):
    """PRD 3.5: "The courtroom's calendar is protected without a buffer: the new
    event must not overlap any other `SCHEDULED` event in the same courtroom,
    again treating intervals as half-open so that two events sharing an exact
    boundary sit back-to-back and are allowed; an overlap is rejected with
    `ERR_COURTROOM_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/courtroom_overlap_adjacency_allowed
    """
    office = fx.create_office()
    att_a = fx.create_attorney(office["id"], name="Oac", bar_number="OA2")
    att_b = fx.create_attorney(office["id"], name="Obd", bar_number="OB2")
    room = fx.create_courtroom(name="Room 10", courthouse="Main")
    ca = _assigned_case(office, att_a, "Oc")
    cb = _assigned_case(office, att_b, "Od")
    validate_success(api.create_court_event(
        {"case_id": ca["id"], "courtroom_id": room["id"], "event_type": "PRETRIAL",
         "scheduled_start": "2026-06-10T09:00:00Z", "scheduled_end": "2026-06-10T10:00:00Z"},
        COORD), 201)
    # Starts exactly at prior end 10:00 -> back-to-back allowed.
    ev = validate_success(api.create_court_event(
        {"case_id": cb["id"], "courtroom_id": room["id"], "event_type": "PRETRIAL",
         "scheduled_start": "2026-06-10T10:00:00Z", "scheduled_end": "2026-06-10T11:00:00Z"},
        COORD), 201)
    assert ev["status"] == "SCHEDULED"


# ===========================================================================
# Difficulty: referential (case-not-assigned) beats temporal (double-booked)
# ===========================================================================

def test_courtevent_case_not_assigned_beats_double_booking(api):
    """PRD 3.5: "The parent case must be `ASSIGNED` so that an assigned attorney
    exists to attend, else the request is rejected with `ERR_CASE_NOT_ASSIGNED`;"
    PRD 2.7: "(11) Courtroom double-booking, else `ERR_COURTROOM_DOUBLE_BOOKED`."

    Design: Difficulty/priority_pair_validation_conflict/courtevent_referential_beats_temporal
    """
    office = fx.create_office()
    attorney = fx.create_attorney(office["id"], name="Amy", bar_number="PP2")
    room = fx.create_courtroom(name="Dept 1", courthouse="Main")
    ca = _assigned_case(office, attorney, "Al")
    validate_success(api.create_court_event(
        {"case_id": ca["id"], "courtroom_id": room["id"], "event_type": "ARRAIGNMENT",
         "scheduled_start": "2026-06-10T09:00:00Z", "scheduled_end": "2026-06-10T10:00:00Z"},
        COORD), 201)
    # caseB only SCREENED (never assigned); overlapping slot in the same room.
    cb = _screened_case(office, attorney, "Bo")
    resp = api.create_court_event(
        {"case_id": cb["id"], "courtroom_id": room["id"], "event_type": "ARRAIGNMENT",
         "scheduled_start": "2026-06-10T09:30:00Z", "scheduled_end": "2026-06-10T10:30:00Z"},
        COORD)
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_ASSIGNED.value)


def test_courtevent_for_unassigned_case_creates_no_event(api):
    """PRD 3.5: "The parent case must be `ASSIGNED` so that an assigned attorney
    exists to attend, else the request is rejected with `ERR_CASE_NOT_ASSIGNED`;
    on success the event's `attorney_id` is copied from the case's
    `assigned_attorney_id` at scheduling time."

    Design: Difficulty/priority_pair_validation_conflict/courtevent_referential_beats_temporal
    """
    office = fx.create_office()
    attorney = fx.create_attorney(office["id"], name="Amz", bar_number="PP3")
    room = fx.create_courtroom(name="Dept 2", courthouse="Main")
    cb = _screened_case(office, attorney, "Bz")
    api.create_court_event(
        {"case_id": cb["id"], "courtroom_id": room["id"], "event_type": "ARRAIGNMENT",
         "scheduled_start": "2026-06-10T09:30:00Z", "scheduled_end": "2026-06-10T10:30:00Z"},
        COORD)
    body = api.list_court_events(COORD, params={"case_id": cb["id"]}).json()
    assert body["meta"]["total_count"] == 0


# ===========================================================================
# Corner: event in the past
# ===========================================================================

def test_court_event_in_past_rejected(api):
    """PRD 3.5: "The `scheduled_start` must not lie before the current logical
    clock; a start in the past is rejected with `ERR_EVENT_IN_PAST`."

    Design: Corner/validations/court_event_in_past_rejected
    """
    office = fx.create_office()
    attorney = fx.create_attorney(office["id"], name="Va", bar_number="V1")
    room = fx.create_courtroom(name="Dept 7", courthouse="Main")
    case = _assigned_case(office, attorney, "Vp")
    fx.set_clock("2026-07-01T00:00:00Z")
    resp = api.create_court_event(
        {"case_id": case["id"], "courtroom_id": room["id"], "event_type": "ARRAIGNMENT",
         "scheduled_start": "2026-06-01T09:00:00Z", "scheduled_end": "2026-06-01T10:00:00Z"},
        COORD)
    validate_error(resp, ApiErrorId.ERR_EVENT_IN_PAST.value)


# ===========================================================================
# Corner: end not strictly after start
# ===========================================================================

def test_court_event_end_not_after_start_rejected(api):
    """PRD 3.5: "The `scheduled_end` must be strictly after the
    `scheduled_start`, and a violation is a body malformation rejected with
    `ERR_VALIDATION`."

    Design: Corner/validations/court_event_end_not_after_start_rejected
    """
    office = fx.create_office()
    attorney = fx.create_attorney(office["id"], name="Vc", bar_number="V3")
    room = fx.create_courtroom(name="Dept 8", courthouse="Main")
    case = _assigned_case(office, attorney, "Ve")
    resp = api.create_court_event(
        {"case_id": case["id"], "courtroom_id": room["id"], "event_type": "TRIAL",
         "scheduled_start": "2026-06-12T09:00:00Z", "scheduled_end": "2026-06-12T09:00:00Z"},
        COORD)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Corner: vacate an already-vacated event
# ===========================================================================

def test_vacate_court_event_twice_invalid_transition(api):
    """PRD 3.5: "An `AssignmentCoordinator` may vacate a scheduled event, which
    requires the event to be `SCHEDULED` (else `ERR_COURT_EVENT_NOT_SCHEDULED`)
    and moves it to `VACATED`, releasing its interval so a later event may reuse
    that attorney or courtroom slot."

    Design: Corner/state_machines/vacate_court_event_twice_invalid_transition
    """
    office = fx.create_office()
    attorney = fx.create_attorney(office["id"], name="Sa", bar_number="S1")
    room = fx.create_courtroom(name="Dept 2", courthouse="Main")
    case = _assigned_case(office, attorney, "Sv")
    ev = validate_success(api.create_court_event(
        {"case_id": case["id"], "courtroom_id": room["id"], "event_type": "TRIAL",
         "scheduled_start": "2026-06-11T09:00:00Z", "scheduled_end": "2026-06-11T10:00:00Z"},
        COORD), 201)
    validate_success(api.vacate_court_event(ev["id"], COORD), 200)
    resp = api.vacate_court_event(ev["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_COURT_EVENT_NOT_SCHEDULED.value)
