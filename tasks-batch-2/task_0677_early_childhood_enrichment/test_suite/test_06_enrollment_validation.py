"""Enrollment-time validation: age band, level match, participation, capacity,
membership-active, validation-priority resolution, and cross-entity state gates.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, create_program, create_room, create_instructor, create_session,
    create_active_membership, create_family, create_child, create_membership,
    enroll_child, hold_session,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["studio_admin_headers"]
STAFF = TEST_USERS["front_desk_headers"]


def test_age_band_exact_max_month_is_ineligible(api):
    """PRD §3.4: "The child must be age-eligible: the child's whole-month age at the
    session's start_at must fall within the program's half-open band, at least
    min_age_months and strictly less than max_age_months. A child exactly at
    max_age_months is ineligible. A violation is ERR_AGE_BAND_MISMATCH (HTTP 422)."

    Band [18,36); a child born exactly 36 months before session.start_at is
    INELIGIBLE -> ERR_AGE_BAND_MISMATCH.

    Design: Difficulty/boundary_precision_check/age_band_exact_max_month_is_ineligible_enroll_endpoint
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, min_age_months=18, max_age_months=36, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"],
                             start_at="2026-06-01T09:00:00Z", end_at="2026-06-01T10:00:00Z", capacity=5)
    family, membership = create_active_membership(tier="CORE")
    # born 2023-06-01 => exactly 36 months at 2026-06-01.
    child = create_child(family["id"], full_name="Exactly36mo", birth_date="2023-06-01")
    v0 = get_success_data(api.get_session(session["id"], STAFF))["version"]
    resp = api.create_enrollment(
        f.create_enrollment_payload(child["id"], session["id"], membership["id"], v0, kind="RECURRING"),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_AGE_BAND_MISMATCH.value)


def test_age_band_one_month_below_max_is_eligible(api):
    """PRD §3.4: "at least min_age_months and strictly less than max_age_months. A
    child exactly at max_age_months is ineligible."

    Boundary companion: a child 35 months old (one below the exclusive max of 36)
    is age-eligible and enrolls successfully (201).

    Design: Difficulty/boundary_precision_check/age_band_exact_max_month_is_ineligible_enroll_endpoint
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, min_age_months=18, max_age_months=36, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"],
                             start_at="2026-06-01T09:00:00Z", end_at="2026-06-01T10:00:00Z", capacity=5)
    family, membership = create_active_membership(tier="CORE")
    # born 2023-07-01 => 35 months at 2026-06-01.
    child = create_child(family["id"], full_name="Age35mo", birth_date="2023-07-01")
    v0 = get_success_data(api.get_session(session["id"], STAFF))["version"]
    resp = api.create_enrollment(
        f.create_enrollment_payload(child["id"], session["id"], membership["id"], v0, kind="RECURRING"),
        STAFF,
    )
    enrollment = validate_success(resp, 201)
    assert enrollment["status"] == "ENROLLED"


def test_state_check_beats_capacity_on_trial_into_held_full_session(api):
    """PRD §2.12: "that the target resource is in a state from which the requested
    transition is defined" is check (5), and "session capacity" is check (12).
    PRD §2.12: "A lower-numbered check always surfaces before a higher-numbered one
    when both would fail."
    PRD §3.4: "enrolling into a HELD or CANCELLED session is ERR_INVALID_STATE."

    A capacity-1 session, filled then HELD (enrolled_count stays 1 == capacity), so
    a later TRIAL enroll violates BOTH state (not SCHEDULED) and capacity (full). The
    higher-priority state error wins: ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_capacity_on_cancelled_session_enroll
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"],
                             start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=1)
    family, membership = create_active_membership(tier="CORE")
    child_a = create_child(family["id"], full_name="A", birth_date="2024-01-01")
    child_b = create_child(family["id"], full_name="B", birth_date="2024-02-01")
    enroll_child(child_a["id"], session["id"], membership["id"], kind="RECURRING")
    set_clock("2026-05-10T09:30:00Z")
    hold_session(session["id"], attendance=[])
    v_live = get_success_data(api.get_session(session["id"], STAFF))["version"]
    resp = api.create_enrollment(
        f.create_enrollment_payload(child_b["id"], session["id"], membership["id"], v_live, kind="TRIAL"),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_age_check_beats_fiscal_membership_inactive_on_enroll(api):
    """PRD §2.12: "child age-band eligibility" is check (9) and "membership-active
    fiscal check" is check (11).
    PRD §2.12: "A lower-numbered check always surfaces before a higher-numbered one
    when both would fail."

    A child too old for the band, enrolled against a still-PENDING_PAYMENT
    membership, fails BOTH age (9) and fiscal (11); the lower-numbered age check
    wins: ERR_AGE_BAND_MISMATCH.

    Design: Difficulty/priority_pair_validation_conflict/safety_age_beats_fiscal_membership_inactive_on_enroll
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, min_age_months=6, max_age_months=18, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"],
                             start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5)
    family = create_family()
    child = create_child(family["id"], full_name="TooOld", birth_date="2022-01-01")
    # PENDING_PAYMENT membership (never activated).
    membership = create_membership(family["id"], tier="CORE")
    v0 = get_success_data(api.get_session(session["id"], STAFF))["version"]
    resp = api.create_enrollment(
        f.create_enrollment_payload(child["id"], session["id"], membership["id"], v0, kind="RECURRING"),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_AGE_BAND_MISMATCH.value)


def test_enroll_into_held_session_returns_invalid_state(api):
    """PRD §3.4: "The target session must be SCHEDULED; enrolling into a HELD or
    CANCELLED session is ERR_INVALID_STATE."

    A HELD session rejects a new enrollment with ERR_INVALID_STATE (the only
    failing check, so it surfaces deterministically).

    Design: Difficulty/cross_entity_state_dependency/enroll_blocked_when_session_not_scheduled_pair_enrollment_session
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"],
                             start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5)
    set_clock("2026-05-10T10:30:00Z")
    hold_session(session["id"], attendance=[])
    family, membership = create_active_membership(tier="CORE")
    child = create_child(family["id"], full_name="Late", birth_date="2024-01-01")
    v_live = get_success_data(api.get_session(session["id"], STAFF))["version"]
    resp = api.create_enrollment(
        f.create_enrollment_payload(child["id"], session["id"], membership["id"], v_live, kind="RECURRING"),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_enroll_into_cancelled_session_returns_invalid_state(api):
    """PRD §3.4: "The target session must be SCHEDULED; enrolling into a HELD or
    CANCELLED session is ERR_INVALID_STATE."

    Companion pair-variant: a CANCELLED session (the other non-SCHEDULED terminal
    state) also rejects a new enrollment with ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/enroll_blocked_when_session_not_scheduled_pair_enrollment_session
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"],
                             start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5)
    v_live = get_success_data(api.get_session(session["id"], STAFF))["version"]
    validate_success(api.cancel_session(session["id"], STAFF), 200)
    family, membership = create_active_membership(tier="CORE")
    child = create_child(family["id"], birth_date="2024-01-01")
    resp = api.create_enrollment(
        f.create_enrollment_payload(child["id"], session["id"], membership["id"], v_live, kind="RECURRING"),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_state_check_beats_capacity_returns_409_not_session_full(api):
    """PRD §2.12: "A lower-numbered check always surfaces before a higher-numbered
    one when both would fail."
    PRD §5: the error catalogue lists ERR_INVALID_STATE as HTTP 409.

    Companion on the state-vs-capacity conflict: the returned HTTP status is 409
    (ERR_INVALID_STATE), confirming the state check pre-empts the capacity check.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_capacity_on_cancelled_session_enroll
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"],
                             start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=1)
    family, membership = create_active_membership(tier="CORE")
    child_a = create_child(family["id"], full_name="A", birth_date="2024-01-01")
    child_b = create_child(family["id"], full_name="B", birth_date="2024-02-01")
    enroll_child(child_a["id"], session["id"], membership["id"], kind="RECURRING")
    set_clock("2026-05-10T09:30:00Z")
    hold_session(session["id"], attendance=[])
    v_live = get_success_data(api.get_session(session["id"], STAFF))["version"]
    resp = api.create_enrollment(
        f.create_enrollment_payload(child_b["id"], session["id"], membership["id"], v_live, kind="TRIAL"),
        STAFF,
    )
    assert resp.status_code == 409, f"expected 409 ERR_INVALID_STATE, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_age_check_beats_fiscal_returns_422_not_membership_inactive(api):
    """PRD §2.12: "A lower-numbered check always surfaces before a higher-numbered
    one when both would fail."
    PRD §3.4: "A violation is ERR_AGE_BAND_MISMATCH (HTTP 422)."

    Companion on the age-vs-fiscal conflict: the rejection is HTTP 422
    ERR_AGE_BAND_MISMATCH, confirming the age check pre-empts the membership-active
    fiscal check.

    Design: Difficulty/priority_pair_validation_conflict/safety_age_beats_fiscal_membership_inactive_on_enroll
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, min_age_months=6, max_age_months=18, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"],
                             start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5)
    family = create_family()
    child = create_child(family["id"], full_name="TooOld", birth_date="2022-01-01")
    membership = create_membership(family["id"], tier="CORE")  # PENDING_PAYMENT
    v0 = get_success_data(api.get_session(session["id"], STAFF))["version"]
    resp = api.create_enrollment(
        f.create_enrollment_payload(child["id"], session["id"], membership["id"], v0, kind="RECURRING"),
        STAFF,
    )
    assert resp.status_code == 422, f"expected 422 ERR_AGE_BAND_MISMATCH, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_AGE_BAND_MISMATCH.value)


def test_hold_before_start_time_returns_invalid_state(api):
    """PRD §3.3: "the logical clock must have reached the session's start_at (the
    clock instant must be at or after start_at); a too-early hold is rejected as an
    invalid state, ERR_INVALID_STATE."

    A SCHEDULED session whose start_at is in the future relative to the clock cannot
    be held: ERR_INVALID_STATE.

    Design: Corner/state_machines/hold_before_start_time_returns_invalid_state
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"],
                             start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5)
    resp = api.hold_session(session["id"], {"attendance": []}, STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_hold_already_cancelled_session_returns_invalid_state(api):
    """PRD §3.3: "Holding a session, valid only from SCHEDULED, advances it to HELD."
    PRD §3.3: "A session has two terminal outcomes that fork from SCHEDULED"

    Holding a session already in the terminal CANCELLED state returns
    ERR_INVALID_STATE 409 — no transitions leave CANCELLED.

    Design: Corner/state_machines/hold_already_cancelled_session_returns_invalid_state
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"],
                             start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5)
    validate_success(api.cancel_session(session["id"], STAFF), 200)
    set_clock("2026-05-10T09:30:00Z")
    resp = api.hold_session(session["id"], {"attendance": []}, STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_recurring_enroll_off_level_returns_level_mismatch(api):
    """PRD §3.4: "For a RECURRING enrollment the child must be on-level: the child's
    current_level must equal the session's program level_index, or the request is
    rejected with ERR_LEVEL_MISMATCH (HTTP 422)"

    A RECURRING enroll into a level-1 session by a child whose current_level is still
    0 (but age-eligible for both bands) returns ERR_LEVEL_MISMATCH.

    Design: Corner/validations/recurring_enroll_off_level_returns_level_mismatch
    """
    set_clock("2026-05-01T00:00:00Z")
    prog1 = create_program(level_index=1, tuition_cents=5000)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[1])
    session = create_session(prog1["id"], room["id"], instructor["id"],
                             start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5)
    family, membership = create_active_membership(tier="CORE")
    child = create_child(family["id"], birth_date="2024-01-01")  # current_level 0
    v0 = get_success_data(api.get_session(session["id"], STAFF))["version"]
    resp = api.create_enrollment(
        f.create_enrollment_payload(child["id"], session["id"], membership["id"], v0, kind="RECURRING"),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_LEVEL_MISMATCH.value)


def test_enroll_participation_required_without_adult_returns_error(api):
    """PRD §3.5: "When a session's program has participation_required true, each
    enrolling child must declare its accompanying adult through the
    accompanying_adult field on the enroll request. Omitting accompanying_adult for
    a participation-required program is rejected with ERR_PARTICIPATION_REQUIRED
    (HTTP 422)."

    Enrolling into a participation_required=true program without accompanying_adult
    returns ERR_PARTICIPATION_REQUIRED.

    Design: Corner/validations/participation_required_without_adult_returns_error
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500, participation_required=True)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"],
                             start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5)
    family, membership = create_active_membership(tier="CORE")
    child = create_child(family["id"], birth_date="2024-01-01")
    v0 = get_success_data(api.get_session(session["id"], STAFF))["version"]
    resp = api.create_enrollment(
        f.create_enrollment_payload(child["id"], session["id"], membership["id"], v0, kind="RECURRING"),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_PARTICIPATION_REQUIRED.value)


def test_trial_enroll_at_capacity_returns_session_full(api):
    """PRD §3.4: "A TRIAL request that arrives at capacity is rejected outright with
    ERR_SESSION_FULL (HTTP 409), because a trial cannot occupy a waitlist seat."

    A TRIAL enroll into a full capacity-1 session returns ERR_SESSION_FULL.

    Design: Corner/validations/trial_enroll_at_capacity_returns_session_full
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"],
                             start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=1)
    family, membership = create_active_membership(tier="CORE")
    child_a = create_child(family["id"], full_name="A", birth_date="2024-01-01")
    child_b = create_child(family["id"], full_name="B", birth_date="2024-02-01")
    enroll_child(child_a["id"], session["id"], membership["id"], kind="RECURRING")
    v1 = get_success_data(api.get_session(session["id"], STAFF))["version"]
    resp = api.create_enrollment(
        f.create_enrollment_payload(child_b["id"], session["id"], membership["id"], v1, kind="TRIAL"),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_FULL.value)
