"""Cohort founding/advancement and the admission funnel.

Translates corner-design instances under sections `entities`, `state_machines`,
`validations` (seat-related), and the seat-conservation difficulty invariant.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    NONEXISTENT_UUID,
    create_cohort_payload,
    create_applicant_payload,
    assert_cohort,
    assert_cohort_seat_invariant,
    create_open_cohort,
    admit_applicant,
    enroll_admitted,
    setup_enrolled,
    set_clock,
)

ADMIN = TEST_USERS["admissions_officer_headers"]


def test_create_cohort_returns_201_with_computed_seat_fields():
    """PRD §3.1: "A freshly created cohort begins life in `PLANNING` with `seats_committed` at zero and `seats_available` equal to its `capacity`."

    Design: Corner/entities/create_cohort_returns_201_with_computed_seat_fields
    """
    set_clock("2026-01-01T00:00:00Z", ADMIN)
    resp = api_client.create_cohort(create_cohort_payload(capacity=5), ADMIN)
    data = validate_success(resp, 201)
    assert data["status"] == "PLANNING"
    assert data["seats_committed"] == 0
    assert data["seats_available"] == 5
    assert data["version"] == 1
    assert_cohort(data)


def test_create_cohort_missing_required_field_returns_invalid_request():
    """PRD §2.8: "write endpoints validate that the body is well-formed — required fields present, enum values legal, numeric ranges respected — failing with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_cohort_missing_required_field_returns_invalid_request
    """
    set_clock("2026-01-01T00:00:00Z", ADMIN)
    payload = create_cohort_payload()
    del payload["capacity"]
    resp = api_client.create_cohort(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_cohort_invalid_enum_track_returns_invalid_request():
    """PRD §2.8: "write endpoints validate that the body is well-formed — required fields present, enum values legal, numeric ranges respected — failing with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_cohort_invalid_enum_track_returns_invalid_request
    """
    set_clock("2026-01-01T00:00:00Z", ADMIN)
    resp = api_client.create_cohort(create_cohort_payload(track="BIOLOGY"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_cohort_nonexistent_returns_not_found():
    """PRD §2.8: "Then existence: every path or body resource id must resolve to an existing row (validated left to right per Section 2.6), failing with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_cohort_nonexistent_returns_not_found
    """
    resp = api_client.get_cohort(NONEXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_applicant_status_system_field_ignores_client_input():
    """PRD §3.2: "A new applicant starts in `APPLIED`."

    Design: Corner/entities/applicant_status_system_field_ignores_client_input
    """
    cohort = create_open_cohort()
    resp = api_client.create_applicant(
        create_applicant_payload(cohort["id"], email="sys@example.com"), ADMIN
    )
    data = validate_success(resp, 201)
    assert data["status"] == "APPLIED"


def test_admit_applicant_from_rejected_returns_invalid_state():
    """PRD §2.8: "Then state: a transition attempted from a state in which it is not defined yields `ERR_INVALID_STATE`."
    PRD §3.2: "Rejecting an applicant moves it from `APPLIED` to `REJECTED`, removing them from the funnel."

    Design: Corner/state_machines/admit_applicant_from_rejected_returns_invalid_state
    """
    cohort = create_open_cohort()
    applicant = get_success_data(
        api_client.create_applicant(create_applicant_payload(cohort["id"], email="rej@example.com"), ADMIN)
    )
    get_success_data(api_client.reject_applicant(applicant["id"], ADMIN))
    resp = api_client.admit_applicant(applicant["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_open_cohort_twice_second_returns_invalid_state():
    """PRD §3.1: "any attempt to drive a cohort through a transition not defined from its present state is an `ERR_INVALID_STATE`."

    Design: Corner/state_machines/open_cohort_twice_second_returns_invalid_state
    """
    cohort = create_open_cohort()
    resp = api_client.open_cohort(cohort["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_archived_cohort_terminal_lockdown():
    """PRD §3.1: "any attempt to drive a cohort through a transition not defined from its present state is an `ERR_INVALID_STATE`."

    Design: Corner/state_machines/archived_cohort_terminal_lockdown
    """
    cohort = create_open_cohort()
    coh_id = cohort["id"]
    set_clock("2026-02-01T00:00:00Z", ADMIN)
    get_success_data(api_client.start_cohort(coh_id, ADMIN))
    set_clock("2026-05-01T00:00:00Z", ADMIN)
    get_success_data(api_client.graduate_cohort(coh_id, ADMIN))
    get_success_data(api_client.archive_cohort(coh_id, ADMIN))
    resp = api_client.graduate_cohort(coh_id, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cohort_start_before_start_date_returns_timing():
    """PRD §3.1: "Starting instruction advances the cohort from `OPEN` to `RUNNING` and requires that the current clock has reached or passed `start_date`; otherwise it too fails with `ERR_COHORT_TIMING`."

    Design: Corner/state_machines/cohort_start_before_start_date_returns_timing
    """
    cohort = create_open_cohort()  # clock at 2026-01-01, start_date 2026-02-01
    resp = api_client.start_cohort(cohort["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_COHORT_TIMING.value)


def test_cohort_full_blocks_admit_at_capacity_boundary():
    """PRD §3.2: "Admitting an applicant moves it from `APPLIED` to `ADMITTED`, stamps `admitted_at` with the decision time, and is allowed only when the target cohort is `OPEN` and has at least one seat available; if the cohort has no free seat the admission is rejected with `ERR_COHORT_FULL`."

    Design: Corner/validations/cohort_full_blocks_admit_at_capacity_boundary
    """
    cohort = create_open_cohort(capacity=1)
    a1 = admit_applicant(cohort["id"], email="first@example.com")
    enroll_admitted(a1["id"], "UPFRONT")
    a2 = get_success_data(
        api_client.create_applicant(create_applicant_payload(cohort["id"], email="second@example.com"), ADMIN)
    )
    resp = api_client.admit_applicant(a2["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_COHORT_FULL.value)


def test_cohort_seats_conserved_under_enroll_withdraw():
    """PRD §2.5: "On a Cohort, `seats_committed` plus `seats_available` always equals `capacity`, where `seats_committed` is the count of that cohort's enrollments whose `status` is `ENROLLED`, `ACTIVE`, or `GRADUATED`, and `seats_available` is `capacity` minus `seats_committed`."
    PRD §3.5: "Withdrawing releases the seat by decrementing `seats_committed`, voids any linked `PENDING` ISA contract to `VOIDED`, and opens a **RefundRequest** in `PENDING` status against the withdrawing enrollment."

    Design: Difficulty/compensating_invariant/cohort_seats_conserved_under_enroll_withdraw
    """
    cohort, applicant, enrollment = setup_enrolled("UPFRONT", email="seat@example.com")
    coh_id = cohort["id"]
    # Before withdraw: seat committed.
    before = get_success_data(api_client.get_cohort(coh_id, ADMIN))
    assert before["seats_committed"] == 1
    assert_cohort_seat_invariant(before)

    get_success_data(api_client.withdraw_enrollment(enrollment["id"], ADMIN, {"refund_reason": "COOLING_OFF"}))
    after = get_success_data(api_client.get_cohort(coh_id, ADMIN))
    assert after["seats_committed"] == 0, "seat must be released by withdraw"
    assert after["seats_available"] == 5
    assert after["seats_committed"] + after["seats_available"] == 5
    assert_cohort_seat_invariant(after)


def test_cohort_seats_conserved_invariant_after_enroll():
    """PRD §2.5: "On a Cohort, `seats_committed` plus `seats_available` always equals `capacity`, where `seats_committed` is the count of that cohort's enrollments whose `status` is `ENROLLED`, `ACTIVE`, or `GRADUATED`, and `seats_available` is `capacity` minus `seats_committed`."
    PRD §3.3: "The owning cohort's `seats_committed` increases by one, conserving the seat."

    Design: Difficulty/compensating_invariant/cohort_seats_conserved_under_enroll_withdraw
    """
    cohort, applicant, enrollment = setup_enrolled("UPFRONT", email="seat2@example.com")
    state = get_success_data(api_client.get_cohort(cohort["id"], ADMIN))
    assert state["seats_committed"] == 1
    assert state["seats_available"] == state["capacity"] - 1
    assert state["seats_committed"] + state["seats_available"] == state["capacity"]
    assert_cohort_seat_invariant(state)


def test_list_cohorts_pagination_envelope():
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_cohorts_pagination_envelope
    """
    set_clock("2026-01-01T00:00:00Z", ADMIN)
    get_success_data(api_client.create_cohort(create_cohort_payload(name="C1"), ADMIN))
    get_success_data(api_client.create_cohort(create_cohort_payload(name="C2", track="DATA"), ADMIN))
    resp = api_client.list_cohorts(ADMIN, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_pagination_limit_over_max_returns_validation():
    """PRD §2.3: "A `limit` above 100, a `limit` below 1, or a negative `offset` is rejected with `ERR_VALIDATION`."

    Design: Corner/endpoints/pagination_limit_over_max_returns_validation
    """
    resp = api_client.list_cohorts(ADMIN, params={"limit": 101})
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
