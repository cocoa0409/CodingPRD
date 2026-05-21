"""LeaveInstance lifecycle — logging, void, duplicate-day, overlap.

Covers PRD §3.4 (instance logging, void, uniqueness rules).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_leave_instance,
    create_leave_instance_payload,
    get_leave_case,
    log_instance,
    make_employee_headers,
    setup_approved_case,
    setup_eligible_employee,
    setup_pending_certification_case,
    submit_leave_case,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Logging — PRD §3.4
# ===========================================================================
class TestInstanceLogging:

    def test_log_instance_on_intermittent_case_succeeds(self, api):
        """PRD §3.4: "For cases with a `leave_pattern` of `INTERMITTENT`
        or `REDUCED_SCHEDULE`, individual absences are recorded as
        `LeaveInstance` rows under the case"."""
        _e, _w, employee, case = setup_pending_certification_case(
            leave_pattern="INTERMITTENT",
        )
        h = make_employee_headers(employee["id"])
        resp = api.create_leave_instance(
            case["id"],
            create_leave_instance_payload(
                instance_date="2026-05-01", hours_used=8,
            ),
            h,
        )
        data = validate_success(resp, expected_status=201)
        assert_leave_instance(data)
        assert data["instance_status"] == "PROPOSED", (
            f"PRD §3.4: "
            f"'A `LeaveInstance` begins in `PROPOSED`'; "
            f"got {data['instance_status']!r}"
        )

    def test_log_instance_on_continuous_case_returns_err_instance_not_allowed(
        self, api,
    ):
        """PRD §3.4: "any attempt to log an instance on a continuous
        case is refused with `ERR_INSTANCE_NOT_ALLOWED`"."""
        _e, _w, employee, case = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
            leave_pattern="CONTINUOUS",
        )
        h = make_employee_headers(employee["id"])
        resp = api.create_leave_instance(
            case["id"],
            create_leave_instance_payload(
                instance_date="2026-05-01", hours_used=8,
            ),
            h,
        )
        validate_error(resp, "ERR_INSTANCE_NOT_ALLOWED")

    @pytest.mark.parametrize("hours_used", [0, 25, 30])
    def test_log_instance_with_hours_outside_1_to_24_rejected(
        self, api, hours_used,
    ):
        """PRD §3.4: "any attempt to log an `hours_used` outside the
        1-to-24 range" is refused with `ERR_INSTANCE_NOT_ALLOWED`."""
        _e, _w, employee, case = setup_pending_certification_case(
            leave_pattern="INTERMITTENT",
        )
        h = make_employee_headers(employee["id"])
        resp = api.create_leave_instance(
            case["id"],
            create_leave_instance_payload(
                instance_date="2026-05-01", hours_used=hours_used,
            ),
            h,
        )
        validate_error(resp, "ERR_INSTANCE_NOT_ALLOWED")

    @pytest.mark.parametrize("hours_used", [1, 24])
    def test_log_instance_with_hours_at_boundary_succeeds(
        self, api, hours_used,
    ):
        """PRD §3.4: "an integer `hours_used` strictly between 1 and
        24 inclusive"."""
        _e, _w, employee, case = setup_pending_certification_case(
            leave_pattern="INTERMITTENT",
        )
        h = make_employee_headers(employee["id"])
        resp = api.create_leave_instance(
            case["id"],
            create_leave_instance_payload(
                instance_date="2026-05-01", hours_used=hours_used,
            ),
            h,
        )
        validate_success(resp, expected_status=201)


# ===========================================================================
# Duplicate-day uniqueness — PRD §3.4
# ===========================================================================
class TestDuplicateDay:

    def test_duplicate_day_on_same_case_returns_err_duplicate(self, api):
        """PRD §3.4: "a `(leave_case_id, instance_date)` pair must be
        unique: posting a second instance with the same date on the
        same case yields `ERR_DUPLICATE_INSTANCE_DAY`"."""
        _e, _w, employee, case = setup_pending_certification_case(
            leave_pattern="INTERMITTENT",
        )
        log_instance(
            leave_case_id=case["id"], employee_id=employee["id"],
            instance_date="2026-05-01", hours_used=8,
        )
        h = make_employee_headers(employee["id"])
        resp = api.create_leave_instance(
            case["id"],
            create_leave_instance_payload(
                instance_date="2026-05-01", hours_used=4,
            ),
            h,
        )
        validate_error(resp, "ERR_DUPLICATE_INSTANCE_DAY")


# ===========================================================================
# Cross-case overlap — PRD §3.4
# ===========================================================================
class TestInstanceOverlap:

    def test_same_day_across_two_cases_returns_err_instance_overlap(
        self, api,
    ):
        """PRD §3.4: "across all of a given employee's cases, no two
        `LeaveInstance` rows may share the same `instance_date` if
        both would consume hours in the same leave-year window — this
        catches the case of an employee posting overlapping absences
        against two different `LeaveCase` rows; the violation surfaces
        as `ERR_INSTANCE_OVERLAP`"."""
        employer, worksite, employee = setup_eligible_employee()
        # Two distinct LeaveCases for the same employee, same leave
        # year (CALENDAR 2026), both INTERMITTENT.
        case_a = submit_leave_case(
            employee_id=employee["id"],
            reason="OWN_SERIOUS_HEALTH",
            leave_pattern="INTERMITTENT",
            requested_start_date="2026-05-01",
            expected_end_date="2026-05-31",
        )
        case_b = submit_leave_case(
            employee_id=employee["id"],
            reason="FAMILY_SERIOUS_HEALTH",
            leave_pattern="INTERMITTENT",
            requested_start_date="2026-06-01",
            expected_end_date="2026-06-30",
        )
        # First log on case_a.
        log_instance(
            leave_case_id=case_a["id"], employee_id=employee["id"],
            instance_date="2026-09-05", hours_used=8,
        )
        # Second log on case_b for the same date — should overlap.
        h = make_employee_headers(employee["id"])
        resp = api.create_leave_instance(
            case_b["id"],
            create_leave_instance_payload(
                instance_date="2026-09-05", hours_used=4,
            ),
            h,
        )
        validate_error(resp, "ERR_INSTANCE_OVERLAP")


# ===========================================================================
# Void — PRD §3.4
# ===========================================================================
class TestInstanceVoid:

    def test_void_recomputes_hours_charged(self, api):
        """PRD §3.4: "An `HRSpecialist` may void a single logged
        instance on an approved or active case; the void flips
        `instance_status` to `VOIDED`, recomputes `hours_charged` on
        the parent case from the surviving `APPROVED` instances, and
        re-credits the leave-year bucket accordingly"."""
        ctx = setup_approved_case(
            leave_pattern="INTERMITTENT",
            requested_start_date="2026-05-01",
            expected_end_date="2026-05-31",
            instance_dates_and_hours=[
                ("2026-05-01", 8), ("2026-05-04", 8),
            ],
        )
        # Both instances were promoted to APPROVED; hours_charged=16.
        assert ctx["case"]["hours_charged"] == 16
        # Void one instance.
        first_instance_id = ctx["instances"][0]["id"]
        resp = api.void_leave_instance(
            ctx["case"]["id"], first_instance_id,
            TEST_USERS["hr_specialist_headers"],
        )
        assert resp.status_code == 204, (
            f"PRD §4: DELETE returns 204; got {resp.status_code}: "
            f"{resp.text}"
        )
        refreshed = get_leave_case(ctx["case"]["id"])
        assert refreshed["hours_charged"] == 8, (
            f"hours_charged must be recomputed from surviving APPROVED "
            f"instances (8 remaining); got {refreshed['hours_charged']!r}"
        )
