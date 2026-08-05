"""Conference scheduling and half-open overlap, court citations with the
COURT_REFERRED gate and buffered courtroom overlap, and citation dispositions."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId, fixtures as fx,
    make_court_officer_headers, TEST_USERS,
)

ADMIN = TEST_USERS["administrator_headers"]


def test_conference_overlap_on_assigned_staff_rejected(api):
    """PRD §3.5: "Overlap is evaluated on half-open intervals: the new conference
    conflicts with an existing one when the new start falls before the existing end and
    the existing start falls before the new end. ... A conflict is reported as
    `ERR_CONFERENCE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/conference_staff_adjacency_overlap
    """
    school, staff, student, case = fx.make_assigned_case(api)
    fx.schedule_conference(api, case["id"], "2026-09-10T10:00:00Z", "2026-09-10T11:00:00Z")
    res = api.create_conference(
        case["id"], {"scheduled_start": "2026-09-10T10:30:00Z", "scheduled_end": "2026-09-10T11:30:00Z"}, ADMIN
    )
    validate_error(res, ApiErrorId.ERR_CONFERENCE_OVERLAP.value)


def test_conference_touching_endpoint_allowed(api):
    """PRD §3.5: "Conferences that merely touch at an endpoint — one ending exactly when
    another begins — do not conflict."

    Design: Difficulty/resource_temporal_overlap/conference_staff_adjacency_overlap
    """
    school, staff, student, case = fx.make_assigned_case(api)
    fx.schedule_conference(api, case["id"], "2026-09-10T10:00:00Z", "2026-09-10T11:00:00Z")
    res = api.create_conference(
        case["id"], {"scheduled_start": "2026-09-10T11:00:00Z", "scheduled_end": "2026-09-10T12:00:00Z"}, ADMIN
    )
    data = validate_success(res, 201)
    assert data["status"] == "SCHEDULED"


def test_hearing_buffer_overlap_rejected(api):
    """PRD §3.8: "Two hearings 20 minutes apart in the same courtroom therefore collide,
    while two exactly 30 minutes apart are allowed, since the comparison at the buffer
    edge is strict. A conflict is reported as `ERR_HEARING_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/hearing_courtroom_buffer_overlap
    """
    school, officer, student, case = fx.drive_case_to_court_referred(api)
    fx.make_scheduled_citation(api, case["id"], officer["id"], courtroom_id="CR-2",
                               start="2026-10-05T09:00:00Z", end="2026-10-05T10:00:00Z")
    res = api.create_court_citation(
        case["id"],
        {"courtroom_id": "CR-2", "hearing_start": "2026-10-05T10:20:00Z", "hearing_end": "2026-10-05T11:00:00Z"},
        make_court_officer_headers(officer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_HEARING_OVERLAP.value)


def test_hearing_exactly_at_buffer_edge_allowed(api):
    """PRD §3.8: "two exactly 30 minutes apart are allowed, since the comparison at the
    buffer edge is strict."

    Design: Difficulty/resource_temporal_overlap/hearing_courtroom_buffer_overlap
    """
    school, officer, student, case = fx.drive_case_to_court_referred(api)
    fx.make_scheduled_citation(api, case["id"], officer["id"], courtroom_id="CR-2",
                               start="2026-10-05T09:00:00Z", end="2026-10-05T10:00:00Z")
    res = api.create_court_citation(
        case["id"],
        {"courtroom_id": "CR-2", "hearing_start": "2026-10-05T10:30:00Z", "hearing_end": "2026-10-05T11:30:00Z"},
        make_court_officer_headers(officer["id"]),
    )
    data = validate_success(res, 201)
    assert data["status"] == "SCHEDULED"


def test_citation_filed_when_case_court_referred(api):
    """PRD §3.8: "Filing requires the case's `tier` to be `COURT_REFERRED`; an attempt at
    any lower tier is rejected with `ERR_CASE_NOT_COURT_ELIGIBLE`. ... The citation records
    its `case_id` and begins in `SCHEDULED`."

    Design: Difficulty/cross_entity_state_dependency/citation_requires_court_tier
    """
    school, officer, student, case = fx.drive_case_to_court_referred(api)
    case_now = validate_success(api.get_case(case["id"], ADMIN), 200)
    assert case_now["tier"] == "COURT_REFERRED"
    res = api.create_court_citation(
        case["id"],
        {"courtroom_id": "CR-1", "hearing_start": "2026-10-01T09:00:00Z", "hearing_end": "2026-10-01T10:00:00Z"},
        make_court_officer_headers(officer["id"]),
    )
    data = validate_success(res, 201)
    assert data["status"] == "SCHEDULED"


def test_citation_rejected_when_case_below_court_tier(api):
    """PRD §3.8: "Filing requires the case's `tier` to be `COURT_REFERRED`; an attempt at
    any lower tier is rejected with `ERR_CASE_NOT_COURT_ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/citation_requires_court_tier
    """
    school, student, case = fx.make_school_student_case(api)  # tier NONE
    res = api.create_court_citation(
        case["id"],
        {"courtroom_id": "CR-1", "hearing_start": "2026-10-01T09:00:00Z", "hearing_end": "2026-10-01T10:00:00Z"},
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_CASE_NOT_COURT_ELIGIBLE.value)


def test_citation_heard_missing_disposition_returns_400(api):
    """PRD §3.8: "Marking it `HEARD` requires a `disposition`; if the disposition is
    absent the request is rejected with `ERR_VALIDATION`."

    Design: Corner/endpoints/citation_heard_missing_disposition_returns_400
    """
    school, officer, student, case = fx.drive_case_to_court_referred(api)
    citation = fx.make_scheduled_citation(api, case["id"], officer["id"], courtroom_id="CR-7")
    res = api.transition_court_citation(
        case["id"], citation["id"], {"to_status": "HEARD"}, make_court_officer_headers(officer["id"])
    )
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


def test_conference_double_hold_invalid(api):
    """PRD §3.5: "`HELD`, `NO_SHOW`, and `CANCELLED` are all terminal."

    Design: Corner/state_machines/conference_double_hold_invalid
    """
    school, staff, student, case, conf = fx.make_case_with_held_conference(api)
    res = api.transition_conference(case["id"], conf["id"], {"to_status": "HELD"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_citation_transition_after_withdrawn_rejected(api):
    """PRD §3.8: "`HEARD`, `DISMISSED`, and `WITHDRAWN` are terminal."

    Design: Corner/state_machines/citation_transition_after_withdrawn_returns_409
    """
    school, officer, student, case = fx.drive_case_to_court_referred(api)
    citation = fx.make_scheduled_citation(api, case["id"], officer["id"], courtroom_id="CR-9")
    officer_headers = make_court_officer_headers(officer["id"])
    api.transition_court_citation(case["id"], citation["id"], {"to_status": "WITHDRAWN"}, officer_headers)
    res = api.transition_court_citation(
        case["id"], citation["id"], {"to_status": "HEARD", "disposition": "guilty"}, officer_headers
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
