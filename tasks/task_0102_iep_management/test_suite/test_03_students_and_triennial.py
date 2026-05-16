"""Student creation and the triennial-status / requires_transition_plan
computed fields — PRD §3.1, §3.2, §3.3.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    DUE_SOON_WINDOW_DAYS,
    advance_clock,
    assert_student,
    create_district,
    create_student,
    create_student_payload,
    get_student,
    setup_eligible_student,
    validate_error,
    validate_success,
)


class TestStudentCreate:
    """PRD §3.1: Student creation defaults."""

    def test_create_student_initial_fields(self, api, admin_headers):
        """PRD §3.1: "Upon creation, the student's triennial_status
        and lre_classification are both set to NOT_APPLICABLE, the
        student's current_iep_id and current_eligibility_evaluation_id
        are null, and triennial_reevaluation_due_date is null."

        Claim: a freshly created student has all five computed fields
        at their documented defaults.
        """
        district = create_district()
        res = api.create_student(
            district["id"],
            create_student_payload(
                external_student_number="STU-001",
                date_of_birth="2014-01-01",
                parent_user_id="parent-1",
            ),
            admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_student(data)
        assert data["triennial_status"] == "NOT_APPLICABLE"
        assert data["lre_classification"] == "NOT_APPLICABLE"
        assert data.get("current_iep_id") in (None, "")
        assert data.get("current_eligibility_evaluation_id") in (None, "")
        assert data.get("triennial_reevaluation_due_date") in (None, "")
        assert data["version"] == 1


class TestTriennialStatusBoundaries:
    """PRD §3.2 triennial-status boundary precision."""

    def test_triennial_status_on_track_just_after_finalize(
        self, api, admin_headers,
    ):
        """PRD §3.2: "if the difference is strictly greater than 90
        days, triennial_status is ON_TRACK".
        PRD §3.2: "it becomes ON_TRACK immediately after a fresh
        finalization".

        Claim: immediately after finalizing as ELIGIBLE, the student's
        triennial_status is ON_TRACK (3 years from now is way past
        90 days).
        """
        _district, student, _eval = setup_eligible_student()
        student_now = get_student(student["district_id"], student["id"])
        assert student_now["triennial_status"] == "ON_TRACK"
        assert student_now["triennial_reevaluation_due_date"] is not None

    def test_triennial_status_due_soon_at_90_days(
        self, api, admin_headers,
    ):
        """PRD §3.2: "if the difference is between zero days and 90
        days inclusive, triennial_status is DUE_SOON".
        PRD §3.2: "exactly 90 days remaining is DUE_SOON".

        Claim: advance the clock so that there are exactly 90 days
        until triennial_reevaluation_due_date → DUE_SOON.
        Setup: finalize, then advance 3 years minus 90 days.
        """
        district, student, _eval = setup_eligible_student()
        # finalized_at is today (initial clock 2025-01-01); due
        # date is finalized_at + 3 years = 2028-01-01. Advance by
        # 3*365 - 90 = 1005 days → current_date = 2028-01-01 - 90.
        advance_clock(district["id"], by_days=3 * 365 - 90)
        student_now = get_student(district["id"], student["id"])
        assert student_now["triennial_status"] == "DUE_SOON"

    def test_triennial_status_due_soon_on_due_date(
        self, api, admin_headers,
    ):
        """PRD §3.2: "exactly 0 days remaining (due today) is
        DUE_SOON".

        Claim: advance the clock to the exact due date → DUE_SOON
        (boundary inclusive at 0).
        """
        district, student, _eval = setup_eligible_student()
        # Advance to the due date (3 years from finalize day).
        advance_clock(district["id"], by_days=3 * 365)
        student_now = get_student(district["id"], student["id"])
        assert student_now["triennial_status"] == "DUE_SOON"

    def test_triennial_status_overdue_one_day_past_due(
        self, api, admin_headers,
    ):
        """PRD §3.2: "one day past due is OVERDUE".

        Claim: advance the clock one day past the due date →
        OVERDUE.
        """
        district, student, _eval = setup_eligible_student()
        advance_clock(district["id"], by_days=3 * 365 + 1)
        student_now = get_student(district["id"], student["id"])
        assert student_now["triennial_status"] == "OVERDUE"

    def test_triennial_status_on_track_at_91_days(
        self, api, admin_headers,
    ):
        """PRD §3.2: "exactly 91 days remaining is ON_TRACK".

        Claim: advance the clock so that there are exactly 91 days
        until the due date → ON_TRACK.
        """
        district, student, _eval = setup_eligible_student()
        advance_clock(district["id"], by_days=3 * 365 - 91)
        student_now = get_student(district["id"], student["id"])
        assert student_now["triennial_status"] == "ON_TRACK"


class TestRequiresTransitionPlan:
    """PRD §3.3 transition-plan eligibility."""

    def test_requires_transition_plan_false_before_age_16(
        self, api, admin_headers,
    ):
        """PRD §3.3: "requires_transition_plan becomes true on or
        after the calendar day equal to date_of_birth plus 16
        calendar years ... and only when current_iep_id is non-null."

        Claim: a young student with no IEP has
        requires_transition_plan=false.
        """
        district = create_district()
        student = create_student(
            district["id"],
            date_of_birth="2014-01-01",
        )
        student_now = get_student(district["id"], student["id"])
        assert student_now["requires_transition_plan"] is False

    def test_requires_transition_plan_remains_false_at_16_without_iep(
        self, api, admin_headers,
    ):
        """PRD §3.3: "requires_transition_plan becomes true on or
        after the calendar day equal to date_of_birth plus 16
        calendar years ... AND only when current_iep_id is non-null."

        Claim: at age 16 but with no IEP, the field is false (BOTH
        conjuncts must hold).
        """
        district = create_district()
        student = create_student(
            district["id"],
            date_of_birth="2009-01-01",  # age 16 on initial clock
        )
        student_now = get_student(district["id"], student["id"])
        assert student_now["requires_transition_plan"] is False
