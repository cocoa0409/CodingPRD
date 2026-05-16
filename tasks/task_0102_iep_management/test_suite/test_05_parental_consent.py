"""Parental consent — PRD §3.4.

Covers: scope/target pairings, approve/reject/withdraw transitions,
parent ownership gate, and the consent's append-only shape.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_parental_consent,
    create_consent_payload,
    create_district,
    create_iep,
    create_student,
    get_consent,
    make_parent_headers,
    parent_approve_consent,
    parent_reject_consent,
    setup_active_iep,
    setup_eligible_student,
    validate_error,
    validate_success,
)


class TestConsentScopeTargetPairings:
    """PRD §3.4: fixed pairings between scope and target_resource_type."""

    @pytest.mark.parametrize(
        "scope,target_type",
        [
            ("IEP_IMPLEMENTATION", "RelatedService"),   # IEP_IMPL → IEP only
            ("RELATED_SERVICE", "IEP"),                  # RS → RelatedService only
            ("PLACEMENT_CHANGE", "IEP"),                 # PC → Student only
        ],
    )
    def test_consent_scope_target_mismatch_rejected(
        self, api, teacher_headers, scope, target_type,
    ):
        """PRD §3.4: "The pairings are fixed: scope=EVALUATION pairs
        with target_resource_type=EligibilityEvaluation;
        scope=IEP_IMPLEMENTATION pairs with target_resource_type=IEP;
        scope=RELATED_SERVICE pairs with
        target_resource_type=RelatedService; scope=PLACEMENT_CHANGE
        pairs with target_resource_type=Student. Submitting a
        mismatched pair is rejected as ERR_INVALID_REQUEST."

        Claim: any mismatched (scope, target_type) → ERR_INVALID_REQUEST.
        """
        district, student, _eval, iep, _goal = setup_active_iep()
        res = api.create_parental_consent(
            district["id"], student["id"],
            create_consent_payload(
                scope=scope,
                target_resource_type=target_type,
                target_resource_id=iep["id"],
            ),
            teacher_headers,
        )
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_consent_target_in_different_student_rejected(
        self, api, teacher_headers,
    ):
        """PRD §3.4: "The target_resource_id must point to a resource
        that belongs to the same student and district as the path;
        otherwise ERR_CROSS_STUDENT_REFERENCE applies."

        Claim: creating an IEP_IMPLEMENTATION consent whose target id
        is an IEP belonging to a DIFFERENT student in the same
        district → ERR_CROSS_STUDENT_REFERENCE.
        """
        district, student_a, _eval_a, iep_a, _goal_a = setup_active_iep()
        # Build a second student in the same district.
        _district_b, student_b, _eval_b = setup_eligible_student(
            district_id=district["id"],
        )
        # Try to create a consent on student_b that targets iep_a.
        res = api.create_parental_consent(
            district["id"], student_b["id"],
            create_consent_payload(
                scope="IEP_IMPLEMENTATION",
                target_resource_type="IEP",
                target_resource_id=iep_a["id"],
            ),
            teacher_headers,
        )
        validate_error(res, "ERR_CROSS_STUDENT_REFERENCE")


class TestParentOwnership:
    """PRD §2.1 ERR_PARENT_OWNERSHIP_MISMATCH."""

    def test_parent_approve_with_wrong_user_id_rejected(
        self, api,
    ):
        """PRD §2.1: "every Parent request additionally requires that
        the value of X-User-ID match the parent_user_id recorded on
        the targeted Student. Mismatch is rejected with
        ERR_PARENT_OWNERSHIP_MISMATCH."

        Claim: a Parent whose X-User-ID does not equal the student's
        parent_user_id is rejected even if the consent exists and is
        PENDING.
        """
        from test_helpers import (
            create_evaluation,
            find_pending_consent_for_evaluation,
            request_evaluation_consent,
        )
        district = create_district()
        # Student parent_user_id = "real-parent"; we'll act as a
        # different parent id.
        student = create_student(
            district["id"], parent_user_id="real-parent",
        )
        evaluation = create_evaluation(district["id"], student["id"])
        evaluation = request_evaluation_consent(
            district["id"], student["id"], evaluation["id"],
        )
        consent = find_pending_consent_for_evaluation(
            district["id"], student["id"], evaluation["id"],
        )
        res = api.approve_consent(
            district["id"], student["id"], consent["id"],
            make_parent_headers("imposter-parent"),
        )
        validate_error(res, "ERR_PARENT_OWNERSHIP_MISMATCH")


class TestConsentStateTransitions:
    """PRD §3.4 PENDING / APPROVED / REJECTED / WITHDRAWN."""

    def test_approve_already_approved_consent_rejected(
        self, api,
    ):
        """PRD §3.4: "Approve and reject both require the consent to
        be in PENDING (otherwise ERR_CONSENT_NOT_PENDING)."

        Claim: approving an already-APPROVED consent →
        ERR_CONSENT_NOT_PENDING.
        """
        from test_helpers import (
            create_evaluation,
            find_pending_consent_for_evaluation,
            request_evaluation_consent,
        )
        district = create_district()
        student = create_student(district["id"])
        evaluation = create_evaluation(district["id"], student["id"])
        evaluation = request_evaluation_consent(
            district["id"], student["id"], evaluation["id"],
        )
        consent = find_pending_consent_for_evaluation(
            district["id"], student["id"], evaluation["id"],
        )
        parent_approve_consent(
            district["id"], student["id"], consent["id"],
            parent_user_id=student["parent_user_id"],
        )
        # Now try to approve again.
        res = api.approve_consent(
            district["id"], student["id"], consent["id"],
            make_parent_headers(student["parent_user_id"]),
        )
        validate_error(res, "ERR_CONSENT_NOT_PENDING")

    def test_reject_pending_consent_moves_to_rejected(self, api):
        """PRD §3.4: "Reject simply stamps decided_at and moves the
        consent to REJECTED; no cascade follows."

        Claim: rejection of a PENDING consent flips its status to
        REJECTED.
        """
        from test_helpers import (
            create_evaluation,
            find_pending_consent_for_evaluation,
            request_evaluation_consent,
        )
        district = create_district()
        student = create_student(district["id"])
        evaluation = create_evaluation(district["id"], student["id"])
        request_evaluation_consent(
            district["id"], student["id"], evaluation["id"],
        )
        consent = find_pending_consent_for_evaluation(
            district["id"], student["id"], evaluation["id"],
        )
        parent_reject_consent(
            district["id"], student["id"], consent["id"],
            parent_user_id=student["parent_user_id"],
        )
        c_now = get_consent(
            district["id"], student["id"], consent["id"],
        )
        assert c_now["status"] == "REJECTED"
        assert c_now.get("decided_at") is not None

    def test_withdraw_non_approved_consent_rejected(self, api):
        """PRD §3.4: "Withdrawal applies to a consent currently in
        APPROVED (otherwise ERR_CONSENT_NOT_APPROVED)."

        Claim: withdraw a still-PENDING consent →
        ERR_CONSENT_NOT_APPROVED.
        """
        from test_helpers import (
            create_evaluation,
            find_pending_consent_for_evaluation,
            request_evaluation_consent,
        )
        district = create_district()
        student = create_student(district["id"])
        evaluation = create_evaluation(district["id"], student["id"])
        request_evaluation_consent(
            district["id"], student["id"], evaluation["id"],
        )
        consent = find_pending_consent_for_evaluation(
            district["id"], student["id"], evaluation["id"],
        )
        # consent is still PENDING — withdraw must fail.
        res = api.withdraw_consent(
            district["id"], student["id"], consent["id"],
            make_parent_headers(student["parent_user_id"]),
        )
        validate_error(res, "ERR_CONSENT_NOT_APPROVED")


class TestConsentAppendOnlyShape:
    """PRD §2.4: ParentalConsent is append-only — no updated_at, no
    version."""

    def test_consent_response_lacks_updated_at_and_version(self, api):
        """PRD §2.4: "Two entity types are append-only event records
        and therefore do not carry updated_at or version:
        ParentalConsent (a new consent row is created whenever a
        fresh request must follow an earlier withdrawal) and
        GoalProgressReport".

        Claim: a ParentalConsent response carries id + created_at but
        does NOT carry updated_at or version.
        """
        from test_helpers import (
            create_evaluation,
            find_pending_consent_for_evaluation,
            request_evaluation_consent,
        )
        district = create_district()
        student = create_student(district["id"])
        evaluation = create_evaluation(district["id"], student["id"])
        request_evaluation_consent(
            district["id"], student["id"], evaluation["id"],
        )
        consent = find_pending_consent_for_evaluation(
            district["id"], student["id"], evaluation["id"],
        )
        assert_parental_consent(consent)
        assert "updated_at" not in consent, (
            "ParentalConsent must not carry updated_at per PRD §2.4"
        )
        assert "version" not in consent, (
            "ParentalConsent must not carry version per PRD §2.4"
        )
