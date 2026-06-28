"""Difficulty queue: validation-precedence conflicts, the strict submit-deadline
boundary, cross-entity state dependencies, and the two distinct temporal-overlap
geometries (buffered half-open appointment vs closed adjacency-allowed contract).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_counselor_headers,
    ApiErrorId,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f


# ==========================================================================
# priority_pair_validation_conflict / forbidden_beats_invalid_state_on_submit
# ==========================================================================
def test_forbidden_beats_invalid_state_on_submit(api):
    """PRD §2.10: "then authorization, including ownership — a role acting where
    it may not, or on a resource it does not own, yields `ERR_FORBIDDEN`; then
    the existence of every path-referenced resource, yielding `ERR_NOT_FOUND`"
    PRD §2.10: "a transition requested on a resource in the wrong state is
    rejected for the wrong state before any deeper business rule is consulted."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_invalid_state_on_submit
    """
    # Owner counselor c_a; second counselor c_b who does NOT own the student.
    counselor_a, student, app = fx.setup_application_in_progress(
        round="RD", deadline_utc="2027-01-01T00:00:00Z",
        student_overrides={"gpa": 3.6, "sat_total": 1300},
    )
    # Roll prep back: the application is in IN_PROGRESS (not READY), so submit would be invalid-state.
    # Create the non-owning counselor.
    counselor_b = fx.create_counselor(full_name="C9B", email="c9b@x.com", hourly_rate_cents=18000)
    ch_b = make_counselor_headers(counselor_b["id"])
    # c_b submits an application it does not own AND which is in the wrong prep state.
    resp = api.submit_application(app["id"], ch_b)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_forbidden_returned_even_when_state_also_invalid(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to
    perform the requested operation — or is permitted in general but is acting on
    a resource it does not own — the request is rejected with `ERR_FORBIDDEN`."
    PRD §2.10: "a transition requested on a resource in the wrong state is
    rejected for the wrong state before any deeper business rule is consulted."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_invalid_state_on_submit
    """
    counselor_a, student, app = fx.setup_application_in_progress(
        round="RD", deadline_utc="2027-01-01T00:00:00Z",
        student_overrides={"gpa": 3.6, "sat_total": 1300},
    )
    counselor_b = fx.create_counselor(full_name="C9B2", email="c9b2@x.com", hourly_rate_cents=18000)
    ch_b = make_counselor_headers(counselor_b["id"])
    resp = api.submit_application(app["id"], ch_b)
    assert resp.status_code == 403
    body = resp.json()
    assert body["data"]["error_id"] == ApiErrorId.ERR_FORBIDDEN.value


# ==========================================================================
# priority_pair_validation_conflict / invalid_request_beats_task_due_after_deadline
# ==========================================================================
def test_invalid_request_beats_task_due_after_deadline(api):
    """PRD §2.10: "then general body well-formedness, yielding
    `ERR_INVALID_REQUEST`; then, where applicable, the contract billing-model
    coherence check yielding `ERR_BILLING_MODEL_INCOHERENT`"
    PRD §2.6: "A malformed body — a missing required field, an unrecognized enum
    value, or an out-of-range number — is rejected with `ERR_INVALID_REQUEST`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_request_beats_task_due_after_deadline
    """
    counselor, student, app = fx.setup_application_in_progress(
        round="RD", deadline_utc="2027-01-01T00:00:00Z",
        student_overrides={"gpa": 3.6, "sat_total": 1300},
    )
    ch = make_counselor_headers(counselor["id"])
    # Bad enum task_type AND due_utc after the deadline: malformed-body wins.
    resp = api.create_application_task(
        {
            "application_id": app["id"], "title": "Bad task", "task_type": "BOGUS",
            "due_utc": "2027-02-01T00:00:00Z", "blocks_submission": True,
        },
        ch,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_malformed_enum_reported_before_temporal_due_check(api):
    """PRD §2.6: "Before any reference check, the request body itself must be
    well-formed: all required fields present, every enum carrying one of its
    permitted values, and every numeric field within its allowed range."
    PRD §3.4: "A task's `due_utc` must be on or before the parent application's
    `deadline_utc` (equal is allowed); a later due date is rejected with
    `ERR_TASK_DUE_AFTER_DEADLINE`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_request_beats_task_due_after_deadline
    """
    counselor, student, app = fx.setup_application_in_progress(
        round="RD", deadline_utc="2027-01-01T00:00:00Z",
        student_overrides={"gpa": 3.6, "sat_total": 1300},
    )
    ch = make_counselor_headers(counselor["id"])
    resp = api.create_application_task(
        {
            "application_id": app["id"], "title": "Bad task", "task_type": "BOGUS",
            "due_utc": "2027-02-01T00:00:00Z", "blocks_submission": True,
        },
        ch,
    )
    assert resp.status_code == 400
    assert resp.json()["data"]["error_id"] == ApiErrorId.ERR_INVALID_REQUEST.value


# ==========================================================================
# boundary_precision_check / submit_deadline_strict_boundary_now_equals_deadline
# ==========================================================================
def test_submit_rejected_when_clock_equals_deadline(api):
    """PRD §3.4: "Submitting moves `prep_status` from `READY` to `SUBMITTED`, and
    is permitted only when the logical clock now is strictly before the
    application's `deadline_utc` (otherwise `ERR_DEADLINE_PASSED`) and only when
    `open_task_count` is 0 (otherwise `ERR_OPEN_TASKS_REMAIN`)."

    Design: Difficulty/boundary_precision_check/submit_deadline_strict_boundary_now_equals_deadline
    """
    counselor, student, app = fx.setup_application_ready(
        round="RD", deadline_utc="2027-01-01T00:00:00Z",
        student_overrides={"gpa": 3.6, "sat_total": 1300},
    )
    ch = make_counselor_headers(counselor["id"])
    # Clock set exactly to the deadline: now == deadline is NOT strictly before.
    fx.set_clock("2027-01-01T00:00:00Z")
    resp = api.submit_application(app["id"], ch)
    validate_error(resp, ApiErrorId.ERR_DEADLINE_PASSED.value)


def test_submit_at_deadline_boundary_is_not_strictly_before(api):
    """PRD §3.4: "Submitting moves `prep_status` from `READY` to `SUBMITTED`, and
    is permitted only when the logical clock now is strictly before the
    application's `deadline_utc` (otherwise `ERR_DEADLINE_PASSED`)"
    PRD §2.4: "At server startup the logical clock reads exactly
    `2026-04-01T00:00:00Z`, and it holds that value until a `PlatformAdmin`
    advances it; before any clock-setting call the clock never falls back to real
    time."

    Design: Difficulty/boundary_precision_check/submit_deadline_strict_boundary_now_equals_deadline
    """
    counselor, student, app = fx.setup_application_ready(
        round="RD", deadline_utc="2027-01-01T00:00:00Z",
        student_overrides={"gpa": 3.6, "sat_total": 1300},
    )
    ch = make_counselor_headers(counselor["id"])
    fx.set_clock("2027-01-01T00:00:00Z")
    resp = api.submit_application(app["id"], ch)
    assert resp.status_code == 409
    assert resp.json()["data"]["error_id"] == ApiErrorId.ERR_DEADLINE_PASSED.value


# ==========================================================================
# cross_entity_state_dependency / start_prep_requires_school_selected
# ==========================================================================
def test_start_prep_rejected_when_school_still_candidate(api):
    """PRD §3.4: "Starting prep moves `prep_status` from `NOT_STARTED` to
    `IN_PROGRESS`, but only if the `SchoolListItem` referenced by the
    application's `school_list_item_id` is in `SELECTED` status, otherwise it is
    rejected with `ERR_SCHOOL_NOT_SELECTED`"

    Design: Difficulty/cross_entity_state_dependency/start_prep_requires_school_selected
    """
    counselor, student = fx.setup_counselor_and_student(
        student_overrides={"gpa": 3.6, "sat_total": 1300}
    )
    ch = make_counselor_headers(counselor["id"])
    # CANDIDATE school never selected.
    item = get_success_data(
        api_client.create_school_list_item(
            f.create_school_list_item_payload(student["id"], school_name="Cand U",
                                              admit_rate=0.50, median_sat=1250, round="RD"),
            ch,
        )
    )
    app = get_success_data(
        api_client.create_application(
            f.create_application_payload(student["id"], item["id"], "RD"), ch
        )
    )
    resp = api.start_prep_application(app["id"], ch)
    validate_error(resp, ApiErrorId.ERR_SCHOOL_NOT_SELECTED.value)


def test_start_prep_school_not_selected_is_conflict(api):
    """PRD §3.2: "A `CANDIDATE` may be selected into the working list,
    transitioning it to `SELECTED` (the list-membership state)"
    PRD §3.4: "only if the `SchoolListItem` referenced by the application's
    `school_list_item_id` is in `SELECTED` status, otherwise it is rejected with
    `ERR_SCHOOL_NOT_SELECTED`"

    Design: Difficulty/cross_entity_state_dependency/start_prep_requires_school_selected
    """
    counselor, student = fx.setup_counselor_and_student(
        student_overrides={"gpa": 3.6, "sat_total": 1300}
    )
    ch = make_counselor_headers(counselor["id"])
    item = get_success_data(
        api_client.create_school_list_item(
            f.create_school_list_item_payload(student["id"], school_name="Cand U2",
                                              admit_rate=0.50, median_sat=1250, round="RD"),
            ch,
        )
    )
    app = get_success_data(
        api_client.create_application(
            f.create_application_payload(student["id"], item["id"], "RD"), ch
        )
    )
    resp = api.start_prep_application(app["id"], ch)
    assert resp.status_code == 409


# ==========================================================================
# cross_entity_state_dependency / scholarship_accept_requires_application_admitted
# ==========================================================================
def test_accept_merit_award_rejected_when_application_pending(api):
    """PRD §3.6: "Accepting a `MERIT` or `NEED` award requires that the tied
    application's `decision_status` is `ADMITTED`, otherwise the acceptance is
    rejected with `ERR_AWARD_NOT_ADMITTED`; an `EXTERNAL` award carries no such
    precondition."

    Design: Difficulty/cross_entity_state_dependency/scholarship_accept_requires_application_admitted
    """
    counselor, student, app = fx.setup_application_submitted(
        round="RD", deadline_utc="2027-01-01T00:00:00Z", submit_clock="2026-12-01T00:00:00Z",
        student_overrides={"gpa": 3.8, "sat_total": 1450},
    )
    ch = make_counselor_headers(counselor["id"])
    assert app["decision_status"] == "PENDING"
    award = get_success_data(
        api_client.create_scholarship(
            f.create_scholarship_payload(student["id"], award_type="MERIT",
                                         gross_amount_cents=1000000, award_name="Merit",
                                         application_id=app["id"]),
            ch,
        )
    )
    resp = api.transition_scholarship(award["id"], {"to_status": "ACCEPTED"}, ch)
    validate_error(resp, ApiErrorId.ERR_AWARD_NOT_ADMITTED.value)


def test_merit_accept_blocked_until_tied_application_admitted(api):
    """PRD §3.6: "Accepting a `MERIT` or `NEED` award requires that the tied
    application's `decision_status` is `ADMITTED`, otherwise the acceptance is
    rejected with `ERR_AWARD_NOT_ADMITTED`"
    PRD §3.6: "An award begins in `OFFERED`, and recording it recomputes the net
    amounts for the student's awards."

    Design: Difficulty/cross_entity_state_dependency/scholarship_accept_requires_application_admitted
    """
    counselor, student, app = fx.setup_application_submitted(
        round="RD", deadline_utc="2027-01-01T00:00:00Z", submit_clock="2026-12-01T00:00:00Z",
        student_overrides={"gpa": 3.8, "sat_total": 1450},
    )
    ch = make_counselor_headers(counselor["id"])
    award = get_success_data(
        api_client.create_scholarship(
            f.create_scholarship_payload(student["id"], award_type="MERIT",
                                         gross_amount_cents=1000000, award_name="Merit2",
                                         application_id=app["id"]),
            ch,
        )
    )
    resp = api.transition_scholarship(award["id"], {"to_status": "ACCEPTED"}, ch)
    assert resp.status_code == 409
    assert resp.json()["data"]["error_id"] == ApiErrorId.ERR_AWARD_NOT_ADMITTED.value


# ==========================================================================
# resource_temporal_overlap / appointment_buffered_halfopen_overlap_rejected
# ==========================================================================
def test_appointment_within_buffer_gap_conflicts(api):
    """PRD §3.8: "A 15-minute buffer is applied symmetrically: the new
    appointment's effective window runs from 15 minutes before its `start_utc` to
    15 minutes after its `end_utc`. The new booking conflicts when that buffered
    low end is strictly before an existing appointment's `end_utc` and that
    existing appointment's `start_utc` is strictly before the buffered high end;
    touching exactly at the buffered boundary does not conflict, but anything
    closer does. A conflict is rejected with `ERR_APPOINTMENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/appointment_buffered_halfopen_overlap_rejected
    """
    counselor, student = fx.setup_counselor_and_student(
        student_overrides={"gpa": 3.6, "sat_total": 1300}
    )
    ch = make_counselor_headers(counselor["id"])
    get_success_data(
        api_client.create_appointment(
            f.create_appointment_payload(student["id"], "2026-05-01T09:00:00Z",
                                         "2026-05-01T10:00:00Z", "STRATEGY"),
            ch,
        )
    )
    # New 10:10-10:40: only a 10-min gap from the 10:00 end < the 15-min buffer => conflict.
    resp = api.create_appointment(
        f.create_appointment_payload(student["id"], "2026-05-01T10:10:00Z",
                                     "2026-05-01T10:40:00Z", "CHECK_IN"),
        ch,
    )
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_OVERLAP.value)


def test_appointment_overlap_is_conflict_status(api):
    """PRD §3.8: "Booking enforces a buffered overlap check on the counselor's
    calendar. The resource under contention is the counselor identified by the
    appointment's `counselor_id`, and the candidate set is every other
    appointment for that same counselor whose status is `BOOKED` or `COMPLETED`."

    Design: Difficulty/resource_temporal_overlap/appointment_buffered_halfopen_overlap_rejected
    """
    counselor, student = fx.setup_counselor_and_student(
        student_overrides={"gpa": 3.6, "sat_total": 1300}
    )
    ch = make_counselor_headers(counselor["id"])
    get_success_data(
        api_client.create_appointment(
            f.create_appointment_payload(student["id"], "2026-05-01T09:00:00Z",
                                         "2026-05-01T10:00:00Z", "STRATEGY"),
            ch,
        )
    )
    resp = api.create_appointment(
        f.create_appointment_payload(student["id"], "2026-05-01T10:10:00Z",
                                     "2026-05-01T10:40:00Z", "CHECK_IN"),
        ch,
    )
    assert resp.status_code == 409
    assert resp.json()["data"]["error_id"] == ApiErrorId.ERR_APPOINTMENT_OVERLAP.value


# ==========================================================================
# resource_temporal_overlap / contract_coverage_closed_adjacency_allowed
# ==========================================================================
def test_contract_coverage_adjacent_windows_allowed(api):
    """PRD §3.3: "Windows that merely share a single endpoint instant are adjacent
    and permitted; only a strict interior overlap is rejected, with
    `ERR_CONTRACT_COVERAGE_OVERLAP`. There is no buffer on this check."

    Design: Difficulty/resource_temporal_overlap/contract_coverage_closed_adjacency_allowed
    """
    counselor, student = fx.setup_counselor_and_student(
        student_overrides={"gpa": 3.6, "sat_total": 1300}
    )
    ch = make_counselor_headers(counselor["id"])
    get_success_data(
        api_client.create_contract(
            f.create_contract_payload(student["id"], "HOURLY", hourly_rate_cents=20000,
                                      coverage_start_utc="2026-04-01T00:00:00Z",
                                      coverage_end_utc="2026-12-31T00:00:00Z"),
            ch,
        )
    )
    # Second window starts exactly when the first ends => adjacent => allowed.
    second = validate_success(
        api.create_contract(
            f.create_contract_payload(student["id"], "HOURLY", hourly_rate_cents=20000,
                                      coverage_start_utc="2026-12-31T00:00:00Z",
                                      coverage_end_utc="2027-06-30T00:00:00Z"),
            ch,
        ),
        expected_status=201,
    )
    assert second["status"] == "DRAFT"


def test_contract_adjacent_window_creates_draft(api):
    """PRD §3.3: "Considering every non-`VOID` `EngagementContract` for the same
    student, each window is a closed interval from its `coverage_start_utc` to its
    `coverage_end_utc`. The new window conflicts when the new start is strictly
    before an existing window's end and that existing window's start is strictly
    before the new end."
    PRD §3.3: "A new contract begins in `DRAFT` with all computed balances at 0."

    Design: Difficulty/resource_temporal_overlap/contract_coverage_closed_adjacency_allowed
    """
    counselor, student = fx.setup_counselor_and_student(
        student_overrides={"gpa": 3.6, "sat_total": 1300}
    )
    ch = make_counselor_headers(counselor["id"])
    get_success_data(
        api_client.create_contract(
            f.create_contract_payload(student["id"], "HOURLY", hourly_rate_cents=20000,
                                      coverage_start_utc="2026-04-01T00:00:00Z",
                                      coverage_end_utc="2026-12-31T00:00:00Z"),
            ch,
        )
    )
    resp = api.create_contract(
        f.create_contract_payload(student["id"], "HOURLY", hourly_rate_cents=20000,
                                  coverage_start_utc="2026-12-31T00:00:00Z",
                                  coverage_end_utc="2027-06-30T00:00:00Z"),
        ch,
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["status"] == "DRAFT"
