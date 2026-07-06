"""Validation priority pairs, numeric/temporal boundaries, and cross-entity/temporal
dependencies (depth).

Translates the priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, and resource_temporal_overlap difficulty instances.
"""
import pytest
from test_helpers import (
    get_success_data, validate_error,
    create_program, create_camera, add_calibration, create_owner,
    capture_citation, review_to_cited, set_clock, file_contest,
    schedule_hearing, initiate_payment, settle_to_cleared,
    create_program_payload, create_citation_payload, review_payload,
    create_calibration_payload, create_camera_payload,
    setup_cited_citation, setup_hearing_scheduled,
    TEST_USERS, make_review_officer_headers,
)

SYS = TEST_USERS["system_admin_headers"]
PA = TEST_USERS["program_admin_headers"]
RO = make_review_officer_headers("ro-1")


# ─── priority_pair_validation_conflict ────────────────

def test_calibration_lapsed_beats_owner_lookup_failed(api):
    """PRD §2.10: "Only then are the domain-specific business rules applied: the
    calibration-coverage, no-violation, owner-lookup, contest-window, hearing-time,
    reduction-range, camera-shape, duplicate, nothing-owed, payment-exists, and
    required-field checks described throughout Section 3."

    Design: Difficulty/priority_pair_validation_conflict/calibration_lapsed_beats_owner_lookup_failed
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    # Calibration expires BEFORE event time (lapsed); and NO owner for the plate.
    add_calibration(camera["id"], performed_at_utc="2026-01-01T00:00:00Z",
                    valid_until_utc="2026-04-01T00:00:00Z")
    citation = capture_citation(
        program["id"], camera["id"],
        citation_overrides={"captured_plate_number": "NOOWNER"})
    res = api.review_citation(citation["id"], review_payload("APPROVE"), RO)
    validate_error(res, "ERR_CALIBRATION_LAPSED")
    unchanged = get_success_data(api.get_citation(citation["id"], PA))
    assert unchanged["status"] == "PENDING_REVIEW"


def test_invalid_state_beats_payment_exists_on_void(api):
    """PRD §2.10: "State legality is checked next — whether the requested transition
    is defined from the resource's current state (`ERR_INVALID_STATE`, HTTP 409)".
    PRD §3.8: "A void is permitted only while the citation is in `PENDING_REVIEW`,
    `CITED`, or `DELINQUENT`; from any other state it is rejected with
    `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_payment_exists_on_void
    """
    ctx = setup_cited_citation()
    cit = ctx["citation"]
    payment = initiate_payment(cit["id"], 12500)
    settle_to_cleared(payment["id"])  # citation -> PAID, cleared payment exists
    paid = get_success_data(api.get_citation(cit["id"], PA))
    assert paid["status"] == "PAID"
    res = api.void_citation(cit["id"], PA)
    # PAID is not a valid from-state for void -> state check fires before payment-exists
    validate_error(res, "ERR_INVALID_STATE")
    still_paid = get_success_data(api.get_citation(cit["id"], PA))
    assert still_paid["status"] == "PAID"


def test_void_state_check_first_from_rejected(api):
    """PRD §3.8: "A void is permitted only while the citation is in `PENDING_REVIEW`,
    `CITED`, or `DELINQUENT`; from any other state it is rejected with
    `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_payment_exists_on_void
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    citation = capture_citation(program["id"], camera["id"])
    get_success_data(api.review_citation(citation["id"], review_payload("REJECT"), RO))
    # REJECTED is not a valid from-state for void.
    res = api.void_citation(citation["id"], PA)
    validate_error(res, "ERR_INVALID_STATE")


def test_calibration_lapsed_precedence_second_angle(api):
    """PRD §3.3: "If no such passing coverage exists, the approval is rejected with
    `ERR_CALIBRATION_LAPSED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/calibration_lapsed_beats_owner_lookup_failed
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    add_calibration(camera["id"], performed_at_utc="2026-01-01T00:00:00Z",
                    valid_until_utc="2026-04-01T00:00:00Z")
    # No owner registered for GHOST plate either.
    citation = capture_citation(
        program["id"], camera["id"],
        citation_overrides={"captured_plate_number": "GHOST"})
    res = api.review_citation(citation["id"], review_payload("APPROVE"), RO)
    validate_error(res, "ERR_CALIBRATION_LAPSED")


# ─── boundary_precision_check ─────────────────────────

def test_speed_at_limit_is_no_violation(api):
    """PRD §3.3: "For a speed camera, the captured event is only a violation when
    `measured_speed_mph` is strictly greater than the camera's `speed_limit_mph`; if
    it is equal or lower, the capture is likewise rejected with `ERR_NO_VIOLATION`."

    Design: Difficulty/boundary_precision_check/speed_over_limit_strict_greater_boundary
    """
    program = create_program()
    camera = create_camera(program["id"], intersection_code="SPD-1",
                           camera_type="SPEED", speed_limit_mph=40)
    res = api.create_citation(
        create_citation_payload(program["id"], camera["id"],
                                captured_plate_number="SPD999",
                                measured_speed_mph=40),
        RO)
    validate_error(res, "ERR_NO_VIOLATION")


def test_speed_one_over_limit_is_violation(api):
    """PRD §3.3: "For a speed camera, the captured event is only a violation when
    `measured_speed_mph` is strictly greater than the camera's `speed_limit_mph`; if
    it is equal or lower, the capture is likewise rejected with `ERR_NO_VIOLATION`."

    Design: Difficulty/boundary_precision_check/speed_over_limit_strict_greater_boundary
    """
    program = create_program()
    camera = create_camera(program["id"], intersection_code="SPD-1",
                           camera_type="SPEED", speed_limit_mph=40)
    citation = get_success_data(api.create_citation(
        create_citation_payload(program["id"], camera["id"],
                                captured_plate_number="SPD999",
                                measured_speed_mph=41),
        RO))
    assert citation["status"] == "PENDING_REVIEW"


def test_contest_at_exact_deadline_allowed(api):
    """PRD §3.5: "The contest must also be timely: the current logical clock must be
    at or before the citation's `due_at_utc`; a filing after the due instant is
    rejected with `ERR_CONTEST_WINDOW_CLOSED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/contest_window_inclusive_deadline_boundary
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    add_calibration(camera["id"])
    owner = create_owner(program["id"], plate_number="ABC123")
    set_clock("2026-05-01T09:00:00Z")
    citation = capture_citation(program["id"], camera["id"])
    cited = review_to_cited(citation["id"])
    assert cited["due_at_utc"] == "2026-05-31T09:00:00.000Z"
    # Clock exactly at due instant -> filing is inclusive-allowed.
    set_clock("2026-05-31T09:00:00Z")
    contest = file_contest(citation["id"], owner["id"], owner["portal_access_pin"],
                           cited["version"], ground="NOT_THE_DRIVER",
                           statement="borrowed")
    updated = get_success_data(api.get_citation(citation["id"], PA))
    assert contest["status"] == "SUBMITTED"
    assert updated["status"] == "CONTESTED"


def test_contest_one_past_deadline_rejected(api):
    """PRD §3.5: "the current logical clock must be at or before the citation's
    `due_at_utc`; a filing after the due instant is rejected with
    `ERR_CONTEST_WINDOW_CLOSED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/contest_window_inclusive_deadline_boundary
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    add_calibration(camera["id"])
    owner = create_owner(program["id"], plate_number="ABC123")
    set_clock("2026-05-01T09:00:00Z")
    citation = capture_citation(program["id"], camera["id"])
    cited = review_to_cited(citation["id"])
    # One second past due.
    set_clock("2026-05-31T09:00:01Z")
    from test_helpers import create_contest_payload, make_registered_owner_headers
    res = api.create_contest(
        citation["id"],
        create_contest_payload(owner["id"], owner["portal_access_pin"],
                               cited["version"]),
        make_registered_owner_headers(owner["id"]))
    validate_error(res, "ERR_CONTEST_WINDOW_CLOSED")


# ─── cross_entity_state_dependency ────────────────────

def test_approve_requires_camera_calibration_coverage(api):
    """PRD §3.3: "there must exist a `PASS` calibration record for that camera whose
    `performed_at_utc` is at or before the citation's `event_at_utc` and whose
    `valid_until_utc` is strictly after the `event_at_utc`. If no such passing
    coverage exists, the approval is rejected with `ERR_CALIBRATION_LAPSED` (HTTP
    422)."

    Design: Difficulty/cross_entity_state_dependency/review_approve_requires_camera_calibration_coverage
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    # Only calibration expired before event; owner IS registered (isolates calibration).
    add_calibration(camera["id"], performed_at_utc="2026-01-01T00:00:00Z",
                    valid_until_utc="2026-04-01T00:00:00Z")
    create_owner(program["id"], plate_number="ABC123")
    citation = capture_citation(program["id"], camera["id"])
    res = api.review_citation(citation["id"], review_payload("APPROVE"), RO)
    validate_error(res, "ERR_CALIBRATION_LAPSED")
    unchanged = get_success_data(api.get_citation(citation["id"], PA))
    assert unchanged["status"] == "PENDING_REVIEW"


def test_approve_succeeds_with_valid_calibration_coverage(api):
    """PRD §3.3: "First, the capturing camera must have had valid calibration
    coverage at the moment of the violation: there must exist a `PASS` calibration
    record for that camera whose `performed_at_utc` is at or before the citation's
    `event_at_utc` and whose `valid_until_utc` is strictly after the `event_at_utc`."

    Design: Difficulty/cross_entity_state_dependency/review_approve_requires_camera_calibration_coverage
    """
    ctx = setup_cited_citation()  # calibration 2026-04-01 .. 2026-12-01 covers event
    assert ctx["citation"]["status"] == "CITED"


def test_hearing_rule_valid_when_citation_hearing_scheduled(api):
    """PRD §3.5: "Ruling requires the citation to be `HEARING_SCHEDULED` and the
    hearing to be `SCHEDULED`; otherwise it is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/hearing_rule_requires_citation_hearing_scheduled
    """
    ctx = setup_hearing_scheduled()
    cit = ctx["citation"]
    hearing = ctx["hearing"]
    # Re-read the live citation: scheduling transitioned it CONTESTED -> HEARING_SCHEDULED.
    live_cit = get_success_data(api.get_citation(cit["id"], PA))
    assert live_cit["status"] == "HEARING_SCHEDULED"
    set_clock("2026-05-15T11:00:00Z")
    from test_helpers import rule_hearing
    ruled = rule_hearing(hearing["id"], "UPHELD", hearing["version"],
                         adjudicator_ref="adj-9")
    assert ruled["status"] == "RULED"


# ─── resource_temporal_overlap ────────────────────────

def test_calibration_coverage_gap_at_event_instant(api):
    """PRD §3.3: "whose `valid_until_utc` is strictly after the `event_at_utc`. If no
    such passing coverage exists, the approval is rejected with
    `ERR_CALIBRATION_LAPSED` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/calibration_coverage_gap_at_event_instant
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    # valid_until == event instant -> outside coverage (strict >).
    add_calibration(camera["id"], performed_at_utc="2026-04-01T00:00:00Z",
                    valid_until_utc="2026-05-01T08:00:00Z")
    create_owner(program["id"], plate_number="ABC123")
    citation = capture_citation(
        program["id"], camera["id"],
        citation_overrides={"event_at_utc": "2026-05-01T08:00:00Z"})
    res = api.review_citation(citation["id"], review_payload("APPROVE"), RO)
    validate_error(res, "ERR_CALIBRATION_LAPSED")
    unchanged = get_success_data(api.get_citation(citation["id"], PA))
    assert unchanged["status"] == "PENDING_REVIEW"


def test_calibration_coverage_one_second_after_event_is_valid(api):
    """PRD §3.3: "whose `valid_until_utc` is strictly after the `event_at_utc`."

    Design: Difficulty/resource_temporal_overlap/calibration_coverage_gap_at_event_instant
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    # valid_until one second after event -> inside coverage.
    add_calibration(camera["id"], performed_at_utc="2026-04-01T00:00:00Z",
                    valid_until_utc="2026-05-01T08:00:01Z")
    create_owner(program["id"], plate_number="ABC123")
    citation = capture_citation(
        program["id"], camera["id"],
        citation_overrides={"event_at_utc": "2026-05-01T08:00:00Z"})
    cited = review_to_cited(citation["id"])
    assert cited["status"] == "CITED"


def test_hearing_scheduled_at_exact_now_rejected(api):
    """PRD §3.5: "The `scheduled_at_utc` must be strictly in the future relative to
    the logical clock at scheduling time; a non-future time is rejected with
    `ERR_HEARING_TIME_INVALID` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/hearing_must_be_strictly_future_point_semantics
    """
    ctx = setup_cited_citation()
    cit = ctx["citation"]
    owner = ctx["owner"]
    contest = file_contest(cit["id"], owner["id"], owner["portal_access_pin"],
                           cit["version"])
    set_clock("2026-05-10T00:00:00Z")
    from test_helpers import create_hearing_payload
    res = api.create_hearing(
        contest["id"],
        create_hearing_payload("2026-05-10T00:00:00Z", "adj-9"), PA)
    validate_error(res, "ERR_HEARING_TIME_INVALID")
    updated = get_success_data(api.get_citation(cit["id"], PA))
    assert updated["status"] == "CONTESTED"


def test_hearing_scheduled_one_second_future_allowed(api):
    """PRD §3.5: "The `scheduled_at_utc` must be strictly in the future relative to
    the logical clock at scheduling time; a non-future time is rejected with
    `ERR_HEARING_TIME_INVALID` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/hearing_must_be_strictly_future_point_semantics
    """
    ctx = setup_cited_citation()
    cit = ctx["citation"]
    owner = ctx["owner"]
    contest = file_contest(cit["id"], owner["id"], owner["portal_access_pin"],
                           cit["version"])
    set_clock("2026-05-10T00:00:00Z")
    hearing = schedule_hearing(contest["id"], "2026-05-10T00:00:01Z", "adj-9")
    assert hearing["status"] == "SCHEDULED"
