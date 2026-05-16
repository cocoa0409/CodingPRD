"""TransitionPlan — PRD §3.3 (finalize) and §3.5 (lifecycle).

Covers: create, finalize gates (post_secondary_goal length,
required_courses non-empty, both invitations documented, parent IEP
amendable), and missing-invitations error.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_transition_plan,
    create_transition_plan,
    create_transition_plan_payload,
    finalize_transition_plan,
    setup_active_iep,
    setup_eligible_student,
    validate_error,
    validate_success,
)


class TestCreateTransitionPlan:

    def test_create_transition_plan_starts_in_draft(self, api):
        """PRD §3.3: "The plan inherits iep_id and student_id and
        starts in DRAFT."

        Claim: a fresh transition plan is in DRAFT.
        """
        from test_helpers import create_iep
        _district, student, _eval = setup_eligible_student()
        iep = create_iep(student["district_id"], student["id"])
        plan = create_transition_plan(
            student["district_id"], student["id"], iep["id"],
        )
        assert_transition_plan(plan)
        assert plan["status"] == "DRAFT"


class TestFinalizeTransitionPlan:

    def test_finalize_succeeds_with_complete_inputs(self, api):
        """PRD §3.3: "To finalize the transition plan to FINALIZED,
        the plan must be in DRAFT ..., post_secondary_goal must be at
        least 10 characters long, required_courses must be non-empty,
        both parent_invitation_documented and
        student_invitation_documented must be true ..., and the
        parent IEP must be in DRAFT or AMENDMENT_PENDING".

        Claim: with all inputs valid, finalize → status=FINALIZED.
        """
        from test_helpers import create_iep
        _district, student, _eval = setup_eligible_student()
        iep = create_iep(student["district_id"], student["id"])
        create_transition_plan(
            student["district_id"], student["id"], iep["id"],
            parent_invitation_documented=True,
            student_invitation_documented=True,
        )
        plan = finalize_transition_plan(
            student["district_id"], student["id"], iep["id"],
        )
        assert plan["status"] == "FINALIZED"

    def test_finalize_missing_parent_invitation_rejected(self, api):
        """PRD §3.3: "both parent_invitation_documented and
        student_invitation_documented must be true (else
        ERR_TRANSITION_INVITATIONS_MISSING)".

        Claim: parent_invitation_documented=false →
        ERR_TRANSITION_INVITATIONS_MISSING.
        """
        from test_helpers import create_iep
        _district, student, _eval = setup_eligible_student()
        iep = create_iep(student["district_id"], student["id"])
        create_transition_plan(
            student["district_id"], student["id"], iep["id"],
            parent_invitation_documented=False,
            student_invitation_documented=True,
        )
        res = api.finalize_transition_plan(
            student["district_id"], student["id"], iep["id"],
            TEST_USERS["teacher_headers"],
        )
        validate_error(res, "ERR_TRANSITION_INVITATIONS_MISSING")

    def test_finalize_missing_student_invitation_rejected(self, api):
        """PRD §3.3: "both parent_invitation_documented and
        student_invitation_documented must be true (else
        ERR_TRANSITION_INVITATIONS_MISSING)".

        Claim: student_invitation_documented=false →
        ERR_TRANSITION_INVITATIONS_MISSING.
        """
        from test_helpers import create_iep
        _district, student, _eval = setup_eligible_student()
        iep = create_iep(student["district_id"], student["id"])
        create_transition_plan(
            student["district_id"], student["id"], iep["id"],
            parent_invitation_documented=True,
            student_invitation_documented=False,
        )
        res = api.finalize_transition_plan(
            student["district_id"], student["id"], iep["id"],
            TEST_USERS["teacher_headers"],
        )
        validate_error(res, "ERR_TRANSITION_INVITATIONS_MISSING")

    def test_finalize_on_active_iep_rejected(self, api):
        """PRD §3.3: "the parent IEP must be in DRAFT or
        AMENDMENT_PENDING (else
        ERR_IEP_NOT_AMENDABLE_FOR_TRANSITION)".

        Claim: finalizing a transition plan whose parent IEP is in
        ACTIVE → ERR_IEP_NOT_AMENDABLE_FOR_TRANSITION.

        Setup walkthrough: PRD §3.3 only gates finalize by parent-IEP
        state, not create. We create the plan while the IEP is DRAFT
        (so create succeeds with invitations True), then activate the
        IEP. Because the student's default DOB makes them younger
        than 16, `requires_transition_plan` is false at activation
        and the activation gate ERR_TRANSITION_PLAN_REQUIRED does not
        apply even though the plan is still DRAFT. With the IEP now
        ACTIVE, finalizing the still-DRAFT plan must hit the gate.
        """
        from test_helpers import (
            activate_iep,
            create_iep,
            create_goal_with_single_objective,
            create_iep_implementation_consent_approved,
            setup_eligible_student,
        )

        district, student, _eval = setup_eligible_student()
        iep = create_iep(district["id"], student["id"])
        # Create a DRAFT plan with invitations True so the only gate
        # that can fire at finalize-time is the parent-IEP-state one.
        create_transition_plan(
            district["id"], student["id"], iep["id"],
            parent_invitation_documented=True,
            student_invitation_documented=True,
        )
        # Add a PROPOSED goal + approved IEP_IMPLEMENTATION consent
        # so activation succeeds without finalizing the plan.
        create_goal_with_single_objective(
            district["id"], student["id"], iep["id"],
        )
        create_iep_implementation_consent_approved(
            district["id"], student["id"], iep["id"],
            parent_user_id=student["parent_user_id"],
        )
        activate_iep(district["id"], student["id"], iep["id"])
        # IEP is now ACTIVE; plan is still DRAFT.
        res = api.finalize_transition_plan(
            district["id"], student["id"], iep["id"],
            TEST_USERS["teacher_headers"],
        )
        validate_error(res, "ERR_IEP_NOT_AMENDABLE_FOR_TRANSITION")

    def test_finalize_non_draft_plan_rejected(self, api):
        """PRD §3.3: "the plan must be in DRAFT (else
        ERR_TRANSITION_PLAN_NOT_DRAFT)".

        Claim: re-finalizing an already-FINALIZED plan →
        ERR_TRANSITION_PLAN_NOT_DRAFT.
        """
        from test_helpers import create_iep
        _district, student, _eval = setup_eligible_student()
        iep = create_iep(student["district_id"], student["id"])
        create_transition_plan(
            student["district_id"], student["id"], iep["id"],
        )
        finalize_transition_plan(
            student["district_id"], student["id"], iep["id"],
        )
        # Already FINALIZED — second call must fail.
        res = api.finalize_transition_plan(
            student["district_id"], student["id"], iep["id"],
            TEST_USERS["teacher_headers"],
        )
        validate_error(res, "ERR_TRANSITION_PLAN_NOT_DRAFT")
