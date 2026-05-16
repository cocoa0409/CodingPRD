"""IEP lifecycle — PRD §3.3, §3.5.

Covers: create DRAFT → activate (with all preconditions) → amend →
finalize-amendment cycle → terminal states EXPIRED / REVOKED /
SUPERSEDED.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    IEP_REVIEW_DAYS,
    activate_iep,
    advance_clock,
    assert_iep,
    begin_amendment,
    create_district,
    create_goal_with_single_objective,
    create_iep,
    create_iep_implementation_consent_approved,
    create_student,
    finalize_amendment,
    get_iep,
    get_student,
    setup_active_iep,
    setup_eligible_student,
    validate_error,
    validate_success,
)


class TestIepCreate:
    """PRD §3.3."""

    def test_create_iep_initial_fields(self, api, teacher_headers):
        """PRD §3.3: "On creation the IEP enters DRAFT, its
        scheduled_review_date is set to effective_start_date plus 365
        days, and special_education_minutes_per_week starts at zero."

        Claim: a freshly created IEP is in DRAFT, sets the review
        date 365 days after effective_start_date, and starts with
        zero sped minutes.
        """
        _district, student, _eval = setup_eligible_student()
        iep = create_iep(
            student["district_id"], student["id"],
            effective_start_date="2025-02-01T00:00:00.000Z",
            total_instructional_minutes_per_week=1500,
            total_school_day_minutes_per_week=1875,
        )
        assert_iep(iep)
        assert iep["status"] == "DRAFT"
        assert iep["special_education_minutes_per_week"] == 0
        # Scheduled review date = effective_start_date + 365 days.
        assert iep["scheduled_review_date"][:10] == "2026-02-01"
        assert iep["lre_percentage_instructional"] == 0
        assert iep["lre_percentage_school_day"] == 0


class TestIepActivationPreconditions:
    """PRD §3.3 activation gates."""

    def test_activate_non_draft_iep_rejected(
        self, api, teacher_headers,
    ):
        """PRD §3.3: "Activation succeeds only when every one of the
        following holds; otherwise the named error is returned: the
        IEP is in DRAFT (ERR_IEP_NOT_DRAFT)".

        Claim: trying to activate an already-ACTIVE IEP →
        ERR_IEP_NOT_DRAFT.
        """
        district, student, _eval, iep, _goal = setup_active_iep()
        res = api.activate_iep(
            district["id"], student["id"], iep["id"], teacher_headers,
        )
        validate_error(res, "ERR_IEP_NOT_DRAFT")

    def test_activate_without_eligible_evaluation_rejected(
        self, api, teacher_headers,
    ):
        """PRD §3.3: "the student's current_eligibility_evaluation_id
        resolves to an evaluation in ELIGIBLE (ERR_STUDENT_NOT_ELIGIBLE)".

        Claim: an IEP for a student whose evaluation has never been
        finalized cannot activate.
        """
        district = create_district()
        student = create_student(district["id"])
        # No evaluation finalized — student has no
        # current_eligibility_evaluation_id.
        iep = create_iep(district["id"], student["id"])
        create_goal_with_single_objective(
            district["id"], student["id"], iep["id"],
        )
        create_iep_implementation_consent_approved(
            district["id"], student["id"], iep["id"],
            parent_user_id=student["parent_user_id"],
        )
        res = api.activate_iep(
            district["id"], student["id"], iep["id"], teacher_headers,
        )
        validate_error(res, "ERR_STUDENT_NOT_ELIGIBLE")

    def test_activate_without_iep_consent_rejected(
        self, api, teacher_headers,
    ):
        """PRD §3.3: "a ParentalConsent with scope=IEP_IMPLEMENTATION,
        target_resource_type=IEP, and target_resource_id equal to this
        IEP's id exists in APPROVED (ERR_IEP_CONSENT_NOT_APPROVED)".

        Claim: an IEP with no APPROVED IEP_IMPLEMENTATION consent
        cannot activate.
        """
        district, student, _eval = setup_eligible_student()
        iep = create_iep(district["id"], student["id"])
        create_goal_with_single_objective(
            district["id"], student["id"], iep["id"],
        )
        # Intentionally do NOT create the IEP_IMPLEMENTATION consent.
        res = api.activate_iep(
            district["id"], student["id"], iep["id"], teacher_headers,
        )
        validate_error(res, "ERR_IEP_CONSENT_NOT_APPROVED")

    def test_activate_without_goals_rejected(
        self, api, teacher_headers,
    ):
        """PRD §3.3: "at least one IEPGoal exists on this IEP in
        PROPOSED (ERR_IEP_NO_GOALS)".

        Claim: an IEP with zero goals cannot activate.
        """
        district, student, _eval = setup_eligible_student()
        iep = create_iep(district["id"], student["id"])
        # No goals at all.
        create_iep_implementation_consent_approved(
            district["id"], student["id"], iep["id"],
            parent_user_id=student["parent_user_id"],
        )
        res = api.activate_iep(
            district["id"], student["id"], iep["id"], teacher_headers,
        )
        validate_error(res, "ERR_IEP_NO_GOALS")

    def test_activate_with_future_meeting_rejected(
        self, api, teacher_headers,
    ):
        """PRD §3.3: "meeting_held_at is non-null and is at or before
        the district's current_date (ERR_IEP_MEETING_NOT_HELD)".

        Claim: meeting_held_at in the future → ERR_IEP_MEETING_NOT_HELD.
        """
        district, student, _eval = setup_eligible_student()
        # The initial clock is 2025-01-01; set meeting_held_at well
        # in the future.
        iep = create_iep(
            district["id"], student["id"],
            meeting_held_at="2030-01-01T00:00:00.000Z",
            effective_start_date="2030-02-01T00:00:00.000Z",
        )
        create_goal_with_single_objective(
            district["id"], student["id"], iep["id"],
        )
        create_iep_implementation_consent_approved(
            district["id"], student["id"], iep["id"],
            parent_user_id=student["parent_user_id"],
        )
        res = api.activate_iep(
            district["id"], student["id"], iep["id"], teacher_headers,
        )
        validate_error(res, "ERR_IEP_MEETING_NOT_HELD")


class TestIepActivationSideEffects:
    """PRD §3.3 side effects on success."""

    def test_activation_promotes_proposed_goals_and_sets_current_iep(
        self, api,
    ):
        """PRD §3.3: "On successful activation the IEP enters ACTIVE,
        every IEPGoal on the IEP currently in PROPOSED transitions to
        ACTIVE, the student's current_iep_id becomes this IEP's id".

        Claim: post-activation, the IEP is ACTIVE, its goals are
        ACTIVE, and Student.current_iep_id equals the IEP's id.
        """
        district, student, _eval, iep, goal = setup_active_iep()
        assert iep["status"] == "ACTIVE"
        s_now = get_student(district["id"], student["id"])
        assert s_now["current_iep_id"] == iep["id"]
        # Find the goal we created.
        from test_helpers import get_goal
        g_now = get_goal(
            district["id"], student["id"], iep["id"], goal["id"],
        )
        assert g_now["status"] == "ACTIVE"


class TestAmendmentCycle:
    """PRD §3.3 ACTIVE → AMENDMENT_PENDING → ACTIVE cycle."""

    def test_begin_amendment_moves_to_amendment_pending(self, api):
        """PRD §3.3: "A SpecialEducationTeacher may begin an
        amendment on an ACTIVE IEP, moving it to AMENDMENT_PENDING
        (rejected with ERR_IEP_NOT_ACTIVE if the IEP is not in
        ACTIVE)."

        Claim: begin-amendment on an ACTIVE IEP moves it to
        AMENDMENT_PENDING.
        """
        district, student, _eval, iep, _goal = setup_active_iep()
        begin_amendment(district["id"], student["id"], iep["id"])
        iep_now = get_iep(district["id"], student["id"], iep["id"])
        assert iep_now["status"] == "AMENDMENT_PENDING"

    def test_finalize_amendment_returns_to_active(self, api):
        """PRD §3.3: "Finalizing the amendment moves the IEP back to
        ACTIVE (rejected with ERR_IEP_NOT_AMENDMENT_PENDING if not in
        AMENDMENT_PENDING)."

        Claim: finalize-amendment on an AMENDMENT_PENDING IEP returns
        it to ACTIVE.
        """
        district, student, _eval, iep, _goal = setup_active_iep()
        begin_amendment(district["id"], student["id"], iep["id"])
        finalize_amendment(district["id"], student["id"], iep["id"])
        iep_now = get_iep(district["id"], student["id"], iep["id"])
        assert iep_now["status"] == "ACTIVE"

    def test_begin_amendment_on_non_active_iep_rejected(self, api):
        """PRD §3.3: "rejected with ERR_IEP_NOT_ACTIVE if the IEP is
        not in ACTIVE".

        Claim: begin-amendment on a DRAFT IEP →
        ERR_IEP_NOT_ACTIVE.
        """
        district, student, _eval = setup_eligible_student()
        iep = create_iep(district["id"], student["id"])
        from test_helpers import TEST_USERS
        res = api.begin_iep_amendment(
            district["id"], student["id"], iep["id"],
            TEST_USERS["teacher_headers"],
        )
        validate_error(res, "ERR_IEP_NOT_ACTIVE")

    def test_finalize_amendment_on_non_amendment_pending_rejected(
        self, api,
    ):
        """PRD §3.3: "rejected with ERR_IEP_NOT_AMENDMENT_PENDING if
        not in AMENDMENT_PENDING".

        Claim: finalize-amendment on an ACTIVE IEP →
        ERR_IEP_NOT_AMENDMENT_PENDING.
        """
        district, student, _eval, iep, _goal = setup_active_iep()
        from test_helpers import TEST_USERS
        res = api.finalize_iep_amendment(
            district["id"], student["id"], iep["id"],
            TEST_USERS["teacher_headers"],
        )
        validate_error(res, "ERR_IEP_NOT_AMENDMENT_PENDING")


class TestIepExpiration:
    """PRD §3.5 ACTIVE → EXPIRED via clock advance."""

    def test_clock_advance_past_review_date_expires_iep(self, api):
        """PRD §3.5: "When the deterministic clock has advanced such
        that current_date is at or after scheduled_review_date and
        no superseding IEP has activated in the meantime, the IEP is
        automatically moved to EXPIRED."
        PRD §3.5: "Every IEPGoal on the IEP currently in ACTIVE is
        transitioned to NOT_MET; every RelatedService on the IEP
        currently in ACTIVE is transitioned to SUSPENDED ... the
        student's current_iep_id is cleared to null".

        Claim: advance clock past the 365-day review date → IEP
        becomes EXPIRED and Student.current_iep_id is cleared.
        """
        district, student, _eval, iep, _goal = setup_active_iep(
            effective_start_date="2025-01-15T00:00:00.000Z",
        )
        # initial clock = 2025-01-01; review date = 2026-01-15.
        # Advance ~366 days past creation so we cross the review date.
        advance_clock(district["id"], by_days=400)
        iep_now = get_iep(district["id"], student["id"], iep["id"])
        assert iep_now["status"] == "EXPIRED"
        s_now = get_student(district["id"], student["id"])
        assert s_now.get("current_iep_id") in (None, "")
        assert s_now["lre_classification"] == "NOT_APPLICABLE"
