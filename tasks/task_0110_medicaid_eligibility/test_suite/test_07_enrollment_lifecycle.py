"""Enrollment lifecycle: SUSPEND/REACTIVATE, half-open overlap
semantics, active count invariant.

Exercises PRD §3.4.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock_to,
    assert_enrollment,
    decide_application,
    get_enrollment,
    get_household,
    iso_offset,
    parse_iso,
    server_now_dt,
    setup_approved_application,
    validate_error,
    validate_success,
)


# ===========================================================================
# Suspend / reactivate — PRD §3.4
# ===========================================================================
class TestSuspendReactivate:

    def test_suspend_active_enrollment(self, api, policy_admin_headers):
        """PRD §3.4: "A PolicyAdmin may suspend an ACTIVE enrollment,
        which transitions it to SUSPENDED and decrements the parent
        household's active_enrollment_count."

        Claim: suspend on ACTIVE → status=SUSPENDED and
        active_enrollment_count decremented.
        """
        _sp, household, _, _a, _det, enrollments = setup_approved_application(
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 12_000.00, "frequency": "ANNUAL"},
            ],
        )
        enrollment = enrollments[0]
        h_before = get_household(household["id"])
        before_count = h_before["active_enrollment_count"]
        res = api.suspend_enrollment(enrollment["id"], policy_admin_headers)
        data = validate_success(res)
        assert data["coverage_status"] == "SUSPENDED", (
            f"suspend must transition to SUSPENDED per PRD §3.4; "
            f"got coverage_status={data['coverage_status']!r}"
        )
        h_after = get_household(household["id"])
        assert h_after["active_enrollment_count"] == before_count - 1, (
            "active_enrollment_count must decrement on suspend per PRD §3.4; "
            f"before={before_count}, after={h_after['active_enrollment_count']}"
        )

    def test_reactivate_suspended_enrollment(self, api, policy_admin_headers):
        """PRD §3.4: "A SUSPENDED enrollment may then be reactivated,
        transitioning it back to ACTIVE and incrementing the household's
        active_enrollment_count."

        Claim: reactivate on SUSPENDED → ACTIVE and count incremented.

        # difficulty: compensating_invariant/enrollment_suspend_reactivate_active_count_invariant
        """
        _sp, household, _, _a, _det, enrollments = setup_approved_application(
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 12_000.00, "frequency": "ANNUAL"},
            ],
        )
        enrollment = enrollments[0]
        h_pre = get_household(household["id"])
        pre_count = h_pre["active_enrollment_count"]
        # Suspend.
        api.suspend_enrollment(enrollment["id"], policy_admin_headers)
        h_mid = get_household(household["id"])
        # Reactivate.
        res = api.reactivate_enrollment(
            enrollment["id"], policy_admin_headers,
        )
        data = validate_success(res)
        assert data["coverage_status"] == "ACTIVE"
        h_post = get_household(household["id"])
        # PRD §3.4 conservation: pre_count == post_count.
        assert h_post["active_enrollment_count"] == pre_count, (
            "Conservation: SUSPEND + REACTIVATE must leave "
            "active_enrollment_count unchanged per PRD §3.4 (count is "
            "the set of {ACTIVE, CONTINUOUS_COVERAGE}); "
            f"pre={pre_count}, mid={h_mid['active_enrollment_count']}, "
            f"post={h_post['active_enrollment_count']}"
        )

    def test_suspend_on_terminated_invalid_state(
            self, api, policy_admin_headers):
        """PRD §3.4: "Suspend or reactivate attempts on an enrollment
        in any other state are rejected with ERR_INVALID_STATE."

        Claim: suspend on a non-ACTIVE enrollment (here: already
        SUSPENDED) → ERR_INVALID_STATE.
        """
        _sp, _hh, _, _a, _det, enrollments = setup_approved_application(
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 12_000.00, "frequency": "ANNUAL"},
            ],
        )
        enrollment = enrollments[0]
        api.suspend_enrollment(enrollment["id"], policy_admin_headers)
        res = api.suspend_enrollment(enrollment["id"], policy_admin_headers)
        validate_error(res, "ERR_INVALID_STATE")

    def test_reactivate_on_active_invalid_state(
            self, api, policy_admin_headers):
        """PRD §3.4: "Suspend or reactivate attempts on an enrollment
        in any other state are rejected with ERR_INVALID_STATE."

        Claim: reactivate on an ACTIVE enrollment → ERR_INVALID_STATE.
        """
        _sp, _hh, _, _a, _det, enrollments = setup_approved_application(
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 12_000.00, "frequency": "ANNUAL"},
            ],
        )
        enrollment = enrollments[0]
        res = api.reactivate_enrollment(
            enrollment["id"], policy_admin_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Continuous-coverage flag — PRD §3.4
# ===========================================================================
class TestContinuousCoverageFlag:

    def test_flag_matches_coverage_status(self, api):
        """PRD §3.4: "Each enrollment carries a continuous_coverage_flag
        that is true precisely when its coverage_status is
        CONTINUOUS_COVERAGE."

        Claim: a fresh ACTIVE enrollment has continuous_coverage_flag
        false.
        """
        _sp, _hh, _, _a, _det, enrollments = setup_approved_application(
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 12_000.00, "frequency": "ANNUAL"},
            ],
        )
        e = enrollments[0]
        assert e["coverage_status"] == "ACTIVE"
        assert e["continuous_coverage_flag"] is False, (
            "continuous_coverage_flag must be false on ACTIVE per PRD §3.4"
        )


# ===========================================================================
# active_enrollment_count formula — PRD §3.4
# ===========================================================================
class TestActiveEnrollmentCount:

    def test_count_includes_active_excludes_redet_due(self, api):
        """PRD §3.4: "The household's active_enrollment_count is
        computed as the count of enrollments whose applicant_id belongs
        to one of the household's applicants and whose coverage_status
        is in the set {ACTIVE, CONTINUOUS_COVERAGE}; note that
        REDETERMINATION_DUE does NOT count toward this aggregate."

        Claim: a single ACTIVE enrollment contributes 1; advancing the
        clock and running the sweep (so it flips to REDETERMINATION_DUE)
        decrements the count to 0.
        """
        from test_helpers import (
            advance_to_redetermination_due,
            run_redetermination_sweep,
        )
        _sp, household, _, _a, _det, enrollments = setup_approved_application(
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 12_000.00, "frequency": "ANNUAL"},
            ],
        )
        enrollment = enrollments[0]
        h_before = get_household(household["id"])
        assert h_before["active_enrollment_count"] == 1
        advance_to_redetermination_due(enrollment=enrollment)
        run_redetermination_sweep()
        h_after = get_household(household["id"])
        assert h_after["active_enrollment_count"] == 0, (
            "REDETERMINATION_DUE does NOT count toward "
            "active_enrollment_count per PRD §3.4; got "
            f"active_enrollment_count={h_after['active_enrollment_count']}"
        )
