"""Dispute filing, mediation, resolution cascades (PRD §3.6, §3.8, §3.9).

Covers the SCORING_FAIRNESS dispute cycle and the cascading void of
PAID PrizePayment when CopyrightTransfer is voided.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    PO,
    award_payload,
    create_dispute_payload,
    make_designer_headers,
    resolve_dispute_payload,
    setup_in_final_aggregating,
    setup_paid_prize_payment,
    setup_review_assignment_disputed,
    setup_review_assignment_in_submitted,
    validate_error,
    validate_paginated,
    validate_success,
    void_transfer_payload,
)


class TestDisputeFiling:

    def test_filing_scoring_fairness_dispute_cascades_assignment_to_DISPUTED(self, api):
        """PRD §3.6: 'When a SCORING_FAIRNESS dispute targets a
        REVIEW_ASSIGNMENT, the targeted assignment cascades from
        SUBMITTED to DISPUTED, an AuditEvent with action_kind of
        REVIEW_DISPUTED is emitted, and that score is excluded from
        aggregation until the dispute resolves.'

        Claim: filing a SCORING_FAIRNESS dispute on a SUBMITTED
        ReviewAssignment cascades its status to DISPUTED.

        # difficulty: non_linear_state_machine/review_assignment_dispute_cycle
        """
        ctx = setup_review_assignment_disputed()
        asg = ctx["assignment"]
        asg_after = validate_success(api.get_review_assignment(asg["id"], PO))
        assert asg_after["status"] == "DISPUTED", (
            f"Expected DISPUTED after dispute filing, got {asg_after['status']!r}"
        )


class TestDisputeResolutionCycle:

    def test_rejected_scoring_dispute_reverts_to_SUBMITTED(self, api):
        """PRD §3.6: 'A REJECTED SCORING_FAIRNESS dispute reverts the
        assignment from DISPUTED back to SUBMITTED, re-includes its
        score, and recomputes the affected submission's aggregate.'

        Claim: ReviewAssignment cycle SUBMITTED -> DISPUTED ->
        SUBMITTED closes after a REJECTED resolution.

        # difficulty: non_linear_state_machine/review_assignment_dispute_cycle
        """
        ctx = setup_review_assignment_disputed()
        dispute = ctx["dispute"]
        asg = ctx["assignment"]
        # Start mediation then resolve REJECTED.
        validate_success(api.start_mediation(dispute["id"], PO))
        validate_success(api.resolve_dispute(
            dispute["id"],
            resolve_dispute_payload(outcome="REJECTED"),
            PO,
        ))
        asg_after = validate_success(api.get_review_assignment(asg["id"], PO))
        assert asg_after["status"] == "SUBMITTED", (
            f"REJECTED resolution must revert DISPUTED -> SUBMITTED; "
            f"got {asg_after['status']!r}"
        )

    def test_upheld_scoring_dispute_voids_assignment(self, api):
        """PRD §3.6: 'An UPHELD SCORING_FAIRNESS dispute targeting a
        REVIEW_ASSIGNMENT moves the assignment from DISPUTED to the
        terminal VOIDED.'

        Claim: ReviewAssignment cycle SUBMITTED -> DISPUTED -> VOIDED.
        """
        ctx = setup_review_assignment_disputed()
        dispute = ctx["dispute"]
        asg = ctx["assignment"]
        validate_success(api.start_mediation(dispute["id"], PO))
        validate_success(api.resolve_dispute(
            dispute["id"],
            resolve_dispute_payload(outcome="UPHELD"),
            PO,
        ))
        asg_after = validate_success(api.get_review_assignment(asg["id"], PO))
        assert asg_after["status"] == "VOIDED", (
            f"UPHELD SCORING_FAIRNESS must void the assignment; "
            f"got {asg_after['status']!r}"
        )


class TestAwardBlockedByDisputedAssignment:

    def test_award_with_disputed_final_assignment_rejected(self, api):
        """PRD §3.7: 'If any ReviewAssignment on a final-stage
        submission is currently DISPUTED at the moment the award is
        attempted, the award is rejected with ERR_DISPUTE_PENDING.'

        Claim: an active DISPUTED assignment on the FINAL-stage
        submission rejects /award with ERR_DISPUTE_PENDING.

        # difficulty: cross_entity_state_dependency/project_award_requires_no_disputed_assignment
        """
        ctx = setup_in_final_aggregating(n_submissions=1)
        project = ctx["project"]
        sub = ctx["submissions"][0]
        designer = ctx["designers"][0]
        tier = ctx["tiers"][0]
        # File a SCORING_FAIRNESS dispute against one final-stage assignment.
        final_asgs = [a for a in ctx["final_assignments"]
                      if a.get("submission_id") == sub["id"]]
        target_asg = final_asgs[0]
        validate_success(api.create_dispute(
            create_dispute_payload(
                project_id=project["id"],
                dispute_type="SCORING_FAIRNESS",
                subject_ref_kind="REVIEW_ASSIGNMENT",
                subject_ref_id=target_asg["id"],
                filer_kind="DESIGNER",
                filer_id=designer["id"],
            ),
            make_designer_headers(designer["id"]),
        ), expected_status=201)
        # Attempt /award.
        resp = api.award_project(
            project["id"],
            award_payload(tier_assignments=[
                {"prize_tier_id": tier["id"], "submission_id": sub["id"]},
            ]),
            PO,
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_PENDING.value)


class TestCopyrightVoidCascade:

    def test_upheld_copyright_dispute_reverses_paid_payment(self, api):
        """PRD §3.8: 'From REGISTERED, void is permitted when an UPHELD
        COPYRIGHT or PLAGIARISM dispute targets the submission; this
        path additionally emits an external deregistration request to
        the copyright authority, and the linked PrizePayment cascades
        PAID to REVERSED.'

        Claim: an UPHELD COPYRIGHT dispute against a REGISTERED
        transfer triggers a cascade that leaves CopyrightTransfer
        VOIDED and PrizePayment REVERSED (depth-3 cascade from
        /disputes/{id}/resolve).

        # difficulty: transitive_cascade/dispute_uphold_to_copyright_void_to_payment_reverse_chain
        # difficulty: compensating_invariant/prize_pool_conservation_through_void_and_reverse
        """
        ctx = setup_paid_prize_payment()
        project = ctx["project"]
        transfer = ctx["transfer"]
        pp = ctx["prize_payment"]
        winning_sub = ctx["submissions"][0]
        # Sanity: transfer REGISTERED, payment PAID.
        assert transfer["status"] == "REGISTERED"
        assert pp["status"] == "PAID"

        # File COPYRIGHT dispute targeting the winning submission.
        # PRD §3.8: "From REGISTERED, void is permitted when an UPHELD
        # COPYRIGHT or PLAGIARISM dispute targets the submission" — so
        # the dispute's subject_ref must be the SUBMISSION, not the
        # transfer.
        designer = ctx["designers"][0]
        dispute = validate_success(api.create_dispute(
            create_dispute_payload(
                project_id=project["id"],
                dispute_type="COPYRIGHT",
                subject_ref_kind="SUBMISSION",
                subject_ref_id=winning_sub["id"],
                filer_kind="DESIGNER",
                filer_id=designer["id"],
            ),
            make_designer_headers(designer["id"]),
        ), expected_status=201)
        validate_success(api.start_mediation(dispute["id"], PO))
        validate_success(api.resolve_dispute(
            dispute["id"],
            resolve_dispute_payload(outcome="UPHELD"),
            PO,
        ))
        # PRD §3.8: void called by PlatformOps carries dispute_id.
        validate_success(api.void_transfer(
            transfer["id"],
            void_transfer_payload(dispute_id=dispute["id"]),
            PO,
        ))

        transfer_after = validate_success(
            api.get_copyright_transfer(transfer["id"], PO),
        )
        pp_after = validate_success(api.get_prize_payment(pp["id"], PO))
        assert transfer_after["status"] == "VOIDED", (
            f"CopyrightTransfer must be VOIDED on upheld COPYRIGHT void"
        )
        assert pp_after["status"] == "REVERSED", (
            f"PrizePayment must cascade PAID -> REVERSED on void; "
            f"got {pp_after['status']!r}"
        )


class TestDisputeWithdrawal:

    def test_filer_can_withdraw_own_filed_dispute(self, api):
        """PRD §3.6: 'A filer (Client or Designer) may instead withdraw
        their own dispute from FILED directly to WITHDRAWN, provided
        the withdrawer is the original filer.'

        Claim: a Designer filer can withdraw their FILED dispute,
        leaving status=WITHDRAWN.
        """
        ctx = setup_review_assignment_in_submitted()
        designer = ctx["designer"]
        asg = ctx["assignment"]
        project = ctx["project"]
        dispute = validate_success(api.create_dispute(
            create_dispute_payload(
                project_id=project["id"],
                dispute_type="SCORING_FAIRNESS",
                subject_ref_kind="REVIEW_ASSIGNMENT",
                subject_ref_id=asg["id"],
                filer_kind="DESIGNER",
                filer_id=designer["id"],
            ),
            make_designer_headers(designer["id"]),
        ), expected_status=201)
        # Withdraw before any mediation.
        resp = api.withdraw_dispute(
            dispute["id"], make_designer_headers(designer["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "WITHDRAWN"
