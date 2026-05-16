"""UsdaReimbursementClaim lifecycle: DRAFT → SUBMITTED → FINALIZED or
REJECTED.

PRD §3.7: claim creation requires period_end >= period_start. Submission
requires no other claim in SUBMITTED/FINALIZED overlapping the period
(closed-closed). While SUBMITTED, contained meal-serving records are
locked against voiding. Finalisation snapshots serving_record_ids,
runs chronological replay for final_reimbursement_cents, and increases
District.usda_reimbursement_total_cents.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    api_client,
    assert_usda_claim,
    create_district,
    create_meal_serving,
    create_menu_item,
    create_usda_claim,
    create_usda_claim_payload,
    finalize_usda_claim,
    make_parent_headers,
    reject_usda_claim,
    setup_district_with_family,
    setup_mergeable_claim_period_pair,
    setup_paid_serving_with_balance,
    submit_and_finalize_claim,
    submit_usda_claim,
    top_up_parent_account,
    validate_error,
    validate_success,
    void_meal_serving,
)


# ===========================================================================
# §3.7 Claim creation
# ===========================================================================
class TestClaimCreation:
    """PRD §3.7: AuditOfficer creates a DRAFT claim with a period."""

    def test_create_claim_initial_state_draft(self, api):
        """PRD §3.7: "An AuditOfficer creates a DRAFT claim with a
        period_start and a period_end ... The claim begins life with
        empty serving_record_ids, zero provisional_total_cents, and
        zero final_reimbursement_cents."

        Claim: a freshly created claim has status='DRAFT', empty
        serving_record_ids, and zero totals.
        """
        district = create_district()
        claim = create_usda_claim(
            district=district,
            period_start="2026-01-01T00:00:00.000Z",
            period_end="2026-01-31T00:00:00.000Z",
        )
        assert_usda_claim(claim)
        assert claim["status"] == "DRAFT"
        assert claim["serving_record_ids"] == []
        assert claim["provisional_total_cents"] == 0
        assert claim["final_reimbursement_cents"] == 0

    def test_inverted_period_rejected(self, api, audit_headers):
        """PRD §3.7: "where period_end must be greater than or equal to
        period_start — an inverted period is rejected with
        ERR_VALIDATION."

        Claim: period_end < period_start → ERR_VALIDATION.
        """
        district = create_district()
        res = api.create_usda_claim(
            district["id"],
            create_usda_claim_payload(
                period_start="2026-02-01T00:00:00.000Z",
                period_end="2026-01-01T00:00:00.000Z",
            ),
            audit_headers,
        )
        validate_error(res, "ERR_VALIDATION")


# ===========================================================================
# §3.7 Submission and overlap
# ===========================================================================
class TestClaimSubmission:
    """PRD §3.7: submission requires no overlapping
    SUBMITTED/FINALIZED claim."""

    def test_submit_draft_claim(self, api):
        """PRD §3.7: "An audit officer submits a DRAFT claim."

        Claim: POST /submit on a DRAFT claim → status='SUBMITTED'.
        """
        district = create_district()
        claim = create_usda_claim(
            district=district,
            period_start="2026-03-01T00:00:00.000Z",
            period_end="2026-03-31T00:00:00.000Z",
        )
        submitted = submit_usda_claim(district=district, claim=claim)
        assert submitted["status"] == "SUBMITTED"

    def test_overlap_at_inclusive_boundary_rejected(self, api):
        """PRD §3.7: "The overlap predicate is closed-closed: two
        periods overlap when the existing claim's period_end is greater
        than or equal to the new claim's period_start and the existing
        claim's period_start is less than or equal to the new claim's
        period_end. A submitted-overlap is rejected with
        ERR_CLAIM_PERIOD_OVERLAP."

        Claim: existing.period_end == new.period_start (boundary
        coincidence) → ERR_CLAIM_PERIOD_OVERLAP.

        # difficulty: resource_temporal_overlap/usda_claim_period_overlap_closed_closed_inclusive_endpoints
        # difficulty: cross_entity_state_dependency/usda_claim_finalize_requires_no_concurrent_overlapping_submitted
        """
        district, c1, c2 = setup_mergeable_claim_period_pair(
            boundary_overlap=True,
        )
        res = api.submit_usda_claim(
            district["id"], c2["id"],
            __import__("test_helpers").TEST_USERS["audit_headers"],
        )
        validate_error(res, "ERR_CLAIM_PERIOD_OVERLAP")

    def test_non_overlapping_periods_both_submit_succeed(self, api):
        """PRD §3.7: "no other claim within this district whose status
        is currently SUBMITTED or FINALIZED has a period that overlaps
        the new one."

        Claim: two non-overlapping claims can both reach SUBMITTED.
        """
        district, c1, c2 = setup_mergeable_claim_period_pair(
            boundary_overlap=False,
        )
        # c1 already submitted by fixture. c2 should submit successfully.
        submitted = submit_usda_claim(district=district, claim=c2)
        assert submitted["status"] == "SUBMITTED"

    def test_submit_already_submitted_rejected(self, api, audit_headers):
        """PRD §3.7: "The submission requires the claim to still be
        DRAFT".

        Claim: submit on a SUBMITTED claim → ERR_INVALID_STATE.
        """
        district = create_district()
        claim = create_usda_claim(
            district=district,
            period_start="2026-04-01T00:00:00.000Z",
            period_end="2026-04-30T00:00:00.000Z",
        )
        submit_usda_claim(district=district, claim=claim)
        res = api.submit_usda_claim(
            district["id"], claim["id"], audit_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# §3.7 Finalisation
# ===========================================================================
class TestClaimFinalisation:
    """PRD §3.7: finalisation snapshots serving_record_ids and
    computes final_reimbursement_cents."""

    def test_finalize_submitted_claim_sets_finalized(self, api):
        """PRD §3.7: "An audit officer finalises a SUBMITTED claim."

        Claim: POST /finalize on a SUBMITTED claim → status='FINALIZED'.
        """
        district = create_district()
        claim = create_usda_claim(
            district=district,
            period_start="2026-05-01T00:00:00.000Z",
            period_end="2026-05-31T00:00:00.000Z",
        )
        submit_usda_claim(district=district, claim=claim)
        finalized = finalize_usda_claim(district=district, claim=claim)
        assert finalized["status"] == "FINALIZED"

    def test_finalize_increases_district_total(self, api):
        """PRD §3.7: "On a successful finalisation, the district's
        usda_reimbursement_total_cents increases by the new
        final_reimbursement_cents."

        Claim: District.usda_reimbursement_total_cents grows by
        final_reimbursement_cents after finalize.
        """
        from test_helpers import (
            advance_clock_to,
            setup_student_with_tier,
        )
        # Create a FREE-tier student so the provisional rate is 480
        # cents on reimbursable items.
        district, parent, student, app = setup_student_with_tier(
            target_tier="FREE",
            school_year_start="2026-08-01T00:00:00.000Z",
        )
        item = create_menu_item(
            district=district, full_price_cents=300, reimbursable=True,
        )
        advance_clock_to("2026-09-10T12:00:00.000Z")
        create_meal_serving(
            district=district, student=student, menu_item=item,
        )
        # Build a claim covering 2026-09.
        claim = create_usda_claim(
            district=district,
            period_start="2026-09-01T00:00:00.000Z",
            period_end="2026-09-30T00:00:00.000Z",
        )
        submit_usda_claim(district=district, claim=claim)
        finalized = finalize_usda_claim(district=district, claim=claim)
        # final_reimbursement_cents should be 480 (FREE, reimbursable).
        assert finalized["final_reimbursement_cents"] == 480
        # District total should have grown by 480.
        district_after = api_client.get_district(
            district["id"],
            __import__("test_helpers").TEST_USERS["audit_headers"],
        ).json()["data"]
        assert (
            district_after["usda_reimbursement_total_cents"] == 480
        ), (
            f"expected district total to be 480, got "
            f"{district_after['usda_reimbursement_total_cents']}"
        )


# ===========================================================================
# §3.7 Rejection
# ===========================================================================
class TestClaimRejection:
    """PRD §3.7: rejection releases the lock on contained servings."""

    def test_reject_submitted_claim(self, api):
        """PRD §3.7: "An audit officer may instead transition a
        SUBMITTED claim to the terminal REJECTED state".

        Claim: POST /reject on a SUBMITTED claim → status='REJECTED'.

        # difficulty: non_linear_state_machine/usda_claim_branching_finalize_or_reject
        """
        district = create_district()
        claim = create_usda_claim(
            district=district,
            period_start="2026-06-01T00:00:00.000Z",
            period_end="2026-06-30T00:00:00.000Z",
        )
        submit_usda_claim(district=district, claim=claim)
        rejected = reject_usda_claim(district=district, claim=claim)
        assert rejected["status"] == "REJECTED"

    def test_reject_does_not_change_district_total(self, api):
        """PRD §3.7: "release the lock that the submission placed on
        contained meal servings" — and crucially, rejection does NOT
        mint any cents.
        PRD §3.1: "usda_reimbursement_total_cents is the sum of
        final_reimbursement_cents across every claim under this
        district that has reached the FINALIZED state".

        Claim: a rejected claim does NOT contribute to
        District.usda_reimbursement_total_cents.
        """
        from test_helpers import TEST_USERS
        district = create_district()
        claim = create_usda_claim(
            district=district,
            period_start="2026-07-01T00:00:00.000Z",
            period_end="2026-07-31T00:00:00.000Z",
        )
        submit_usda_claim(district=district, claim=claim)
        reject_usda_claim(district=district, claim=claim)
        district_after = api_client.get_district(
            district["id"], TEST_USERS["audit_headers"],
        ).json()["data"]
        assert district_after["usda_reimbursement_total_cents"] == 0


# ===========================================================================
# §3.7 Locking semantics
# ===========================================================================
class TestSubmittedClaimLocksServings:
    """PRD §3.7 / §3.6: contained meal-serving records are locked
    against voiding while the claim is SUBMITTED."""

    def test_void_locked_serving_rejected(self, api, cafeteria_headers):
        """PRD §3.6: "requires that the record's id is not already
        locked inside a UsdaReimbursementClaim whose status is
        SUBMITTED or FINALIZED ... a void on a locked record is
        rejected with ERR_INVALID_STATE."

        Claim: after a claim covering a serving is SUBMITTED, voiding
        that serving → ERR_INVALID_STATE.
        """
        from test_helpers import (
            advance_clock_to,
            setup_student_with_tier,
        )
        district, parent, student, _app = setup_student_with_tier(
            target_tier="FREE",
            school_year_start="2026-08-01T00:00:00.000Z",
        )
        item = create_menu_item(
            district=district, full_price_cents=300, reimbursable=True,
        )
        advance_clock_to("2026-10-15T12:00:00.000Z")
        serving = create_meal_serving(
            district=district, student=student, menu_item=item,
        )
        # Submit a claim covering 2026-10.
        claim = create_usda_claim(
            district=district,
            period_start="2026-10-01T00:00:00.000Z",
            period_end="2026-10-31T00:00:00.000Z",
        )
        submit_usda_claim(district=district, claim=claim)
        # Attempt to void the contained serving.
        res = api.void_meal_serving(
            district["id"], serving["id"], cafeteria_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_reject_unlocks_contained_servings(self, api):
        """PRD §3.7: "An audit officer may instead transition a
        SUBMITTED claim to the terminal REJECTED state, which releases
        the lock that the submission placed on contained meal servings
        (so subsequent voids on those records become permitted again,
        subject to §3.6's own checks)."

        Claim: after rejecting the claim, voiding the previously-locked
        serving succeeds.
        """
        from test_helpers import (
            advance_clock_to,
            setup_student_with_tier,
        )
        district, parent, student, _app = setup_student_with_tier(
            target_tier="FREE",
            school_year_start="2026-08-01T00:00:00.000Z",
        )
        item = create_menu_item(
            district=district, full_price_cents=300, reimbursable=True,
        )
        advance_clock_to("2026-11-10T12:00:00.000Z")
        serving = create_meal_serving(
            district=district, student=student, menu_item=item,
        )
        claim = create_usda_claim(
            district=district,
            period_start="2026-11-01T00:00:00.000Z",
            period_end="2026-11-30T00:00:00.000Z",
        )
        submit_usda_claim(district=district, claim=claim)
        reject_usda_claim(district=district, claim=claim)
        # Now the serving can be voided.
        voided = void_meal_serving(district=district, serving=serving)
        assert voided["status"] == "VOIDED"
