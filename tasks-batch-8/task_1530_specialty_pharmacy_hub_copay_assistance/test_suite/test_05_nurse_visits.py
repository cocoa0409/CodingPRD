"""Nurse education visits: half-open window overlap per nurse, window shape
validation, outcome enum validation, and assigned-nurse ownership."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_nurse_visit,
    create_enrollment,
    create_nurse_visit_payload,
    create_program,
    get_enrollment,
    make_nurse_educator_headers,
    resolve_visit_payload,
    schedule_visit,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

CM = TEST_USERS["case_manager_headers"]


def _enrollment_with_visit():
    prog = create_program(name="ProgNV",
                          requires_injection_training=True)
    enr = create_enrollment(prog["id"], patient_ref="PAT-P")
    visit = schedule_visit(enr["id"], nurse_id="nurse-1",
                           window_start="2026-08-02T14:00:00Z",
                           window_end="2026-08-02T15:00:00Z")
    return enr, visit


class TestHalfOpenOverlap:

    def test_overlapping_window_for_same_nurse_rejected(self):
        """PRD section 3.5: "Scheduling is conflict-checked per nurse: a new
        window that overlaps another `SCHEDULED` visit for the same
        `nurse_id` under half-open interval comparison is rejected with
        `ERR_VISIT_WINDOW_OVERLAP` (HTTP 409), while merely touching windows
        — one visit's `window_end` equal to the other's `window_start` —
        are permitted."

        Design: Difficulty/resource_temporal_overlap/nurse_visit_half_open_overlap
        """
        enr, _ = _enrollment_with_visit()
        resp = api_client.create_nurse_visit(
            enr["id"],
            create_nurse_visit_payload(
                nurse_id="nurse-1",
                window_start="2026-08-02T14:30:00Z",
                window_end="2026-08-02T15:30:00Z"),
            CM)
        validate_error(resp, ApiErrorId.ERR_VISIT_WINDOW_OVERLAP)

    def test_touching_window_for_same_nurse_accepted(self):
        """PRD section 3.5: "Scheduling is conflict-checked per nurse: a new
        window that overlaps another `SCHEDULED` visit for the same
        `nurse_id` under half-open interval comparison is rejected with
        `ERR_VISIT_WINDOW_OVERLAP` (HTTP 409), while merely touching windows
        — one visit's `window_end` equal to the other's `window_start` —
        are permitted."
        PRD section 3.5: "The window is half-open: it begins at
        `window_start` and ends strictly before `window_end`, and
        `window_end` must fall strictly after `window_start`; an empty or
        inverted window is rejected with `ERR_VISIT_WINDOW_INVALID`."

        Design: Difficulty/resource_temporal_overlap/nurse_visit_half_open_overlap
        """
        enr, _ = _enrollment_with_visit()
        resp = api_client.create_nurse_visit(
            enr["id"],
            create_nurse_visit_payload(
                nurse_id="nurse-1",
                window_start="2026-08-02T15:00:00Z",
                window_end="2026-08-02T16:00:00Z"),
            CM)
        visit = validate_success(resp, expected_status=201)
        assert_nurse_visit(visit)
        assert visit["status"] == "SCHEDULED"


class TestWindowAndOutcomeValidation:

    def test_visit_window_end_before_start_returns_invalid(self):
        """PRD section 3.5: "The window is half-open: it begins at
        `window_start` and ends strictly before `window_end`, and
        `window_end` must fall strictly after `window_start`; an empty or
        inverted window is rejected with `ERR_VISIT_WINDOW_INVALID`."

        Design: Corner/validations/visit_window_end_before_start_returns_invalid
        """
        prog = create_program(name="ProgV5",
                              requires_injection_training=True)
        enr = create_enrollment(prog["id"], patient_ref="PAT-V5")
        resp = api_client.create_nurse_visit(
            enr["id"],
            create_nurse_visit_payload(
                nurse_id="nurse-1",
                window_start="2026-08-02T15:00:00Z",
                window_end="2026-08-02T14:00:00Z"),
            CM)
        validate_error(resp, ApiErrorId.ERR_VISIT_WINDOW_INVALID)

    def test_resolve_visit_invalid_enum_returns_validation(self):
        """PRD section 3.5: "The nurse supplies an `outcome` of `COMPLETED`
        or `NO_SHOW`, and the resolver's identity is recorded in the visit's
        `completed_by_user_id`."
        PRD section 2.6: "Request body schema. Required fields present,
        types valid, enum values in range, and dates parseable — including
        the two date-sanity rules that a `requested_delivery_date` must fall
        on or after the current logical clock date and an `awareness_at`
        must be no later than the current logical clock time; failures yield
        `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/validations/resolve_visit_invalid_enum_returns_validation
        """
        enr, visit = _enrollment_with_visit()
        resp = api_client.resolve_nurse_visit(
            visit["id"], resolve_visit_payload("MAYBE"),
            make_nurse_educator_headers("nurse-1"))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestAssignedNurseOwnership:

    def test_nurse_cannot_resolve_other_nurses_visit(self):
        """PRD section 2.1: "A request whose role is not listed among the
        roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN`; the same code applies when a `NurseEducator`
        attempts to resolve a nurse visit assigned to a different nurse."
        PRD section 3.5: "A visit is born `SCHEDULED`, and only the assigned
        nurse may resolve it: a resolution attempted under any other
        identity is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/nurse_cannot_resolve_other_nurses_visit
        """
        enr, visit = _enrollment_with_visit()
        resp = api_client.resolve_nurse_visit(
            visit["id"], resolve_visit_payload("COMPLETED"),
            make_nurse_educator_headers("nurse-2"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        data, _ = validate_paginated(api_client.list_nurse_visits(enr["id"], CM))
        assert data[0]["status"] == "SCHEDULED", \
            "a forbidden resolution must not mutate the visit"
        enr_after = get_enrollment(enr["id"])
        assert enr_after["training_sessions_completed"] == 0
