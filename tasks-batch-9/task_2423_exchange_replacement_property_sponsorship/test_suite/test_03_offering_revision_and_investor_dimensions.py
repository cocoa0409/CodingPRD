"""Two machines that are not linear chains: one cycles, one runs in parallel.

The offering re-enters `DRAFT` from `UNDER_REVIEW` and counts the visits; the
investor carries accreditation and suitability as two dimensions of one row that
advance without touching each other.
"""

from test_helpers import (
    CANONICAL_CAPITAL_STACK,
    COMPLIANCE,
    INVESTOR_A,
    api_client,
    create_investor,
    declare_offering_effective,
    lapse_accreditation,
    read_investor,
    read_offering,
    return_ppm,
    review_suitability,
    set_clock,
    setup_funding_with_investor_a,
    setup_offering_effective,
    setup_offering_under_review,
    submit_ppm,
    validate_error,
    verify_accreditation,
)


class TestOfferingPpmRevisionCycle:
    def test_returning_the_memorandum_reoccupies_draft_and_raises_the_revision(self):
        """The same node is visited twice and the counter records it.

        PRD: "A `ComplianceOfficer` may return the memorandum for revision with an
        optional `review_note`, moving it `UNDER_REVIEW → DRAFT` and incrementing
        `ppm_version` by exactly 1."

        Design: Difficulty/non_linear_state_machine/offering_ppm_revision_cycle_draft_review_draft_effective
        """
        deal = setup_offering_under_review()
        assert deal["offering"]["status"] == "UNDER_REVIEW"
        assert deal["offering"]["ppm_version"] == 1

        returned = return_ppm(
            deal["offering"]["id"],
            review_note="restate the trustee-power limitations in Item 4",
        )

        assert returned["status"] == "DRAFT"
        assert returned["ppm_version"] == 2

    def test_the_loop_may_be_traversed_and_resubmission_keeps_the_new_revision(self):
        """Resubmitting does not raise the counter a second time.

        PRD: "This is the cyclic edge of the offering machine: the pair may loop
        `DRAFT → UNDER_REVIEW → DRAFT` any number of times, and each return raises
        the revision counter, so a reviewer who read revision 3 and comes back to
        sign off after two more returns is holding a stale document."

        Design: Difficulty/non_linear_state_machine/offering_ppm_revision_cycle_draft_review_draft_effective
        """
        deal = setup_offering_under_review()
        return_ppm(deal["offering"]["id"], review_note="revise Item 4")

        resubmitted = submit_ppm(deal["offering"]["id"], reference="PPM-2423-r2")

        assert resubmitted["status"] == "UNDER_REVIEW"
        assert resubmitted["ppm_version"] == 2

    def test_the_pre_revision_acknowledgement_is_stale_after_one_loop(self):
        """A reviewer holding revision 1 cannot sign off on revision 2.

        PRD: "And the request's `acknowledged_ppm_version` must equal the
        offering's current `ppm_version`, or it is refused with
        `ERR_PPM_VERSION_STALE`."

        Design: Difficulty/non_linear_state_machine/offering_ppm_revision_cycle_draft_review_draft_effective
        """
        deal = setup_offering_under_review()
        return_ppm(deal["offering"]["id"], review_note="revise Item 4")
        submit_ppm(deal["offering"]["id"], reference="PPM-2423-r2")

        response = api_client.declare_offering_effective(
            deal["offering"]["id"], {"acknowledged_ppm_version": 1}, COMPLIANCE
        )
        validate_error(response, "ERR_PPM_VERSION_STALE")

        offering = read_offering(deal["offering"]["id"])
        assert offering["status"] == "UNDER_REVIEW"
        assert offering["ppm_version"] == 2

    def test_declaring_effective_after_the_loop_pins_the_stack_at_revision_two(self):
        """The second traversal ends in `EFFECTIVE` with the revision preserved.

        PRD: "On success `effective_at` is stamped from the logical clock and the
        capital stack is pinned."

        Design: Difficulty/non_linear_state_machine/offering_ppm_revision_cycle_draft_review_draft_effective
        """
        deal = setup_offering_under_review()
        return_ppm(deal["offering"]["id"], review_note="revise Item 4")
        submit_ppm(deal["offering"]["id"], reference="PPM-2423-r2")

        offering = declare_offering_effective(
            deal["offering"]["id"], acknowledged_ppm_version=2
        )

        assert offering["status"] == "EFFECTIVE"
        assert offering["ppm_version"] == 2
        assert offering["target_equity_cents"] == (
            CANONICAL_CAPITAL_STACK["target_equity_cents"]
        )
        assert offering["effective_at"] is not None


class TestInvestorAccreditationAndSuitabilityDimensions:
    def test_verification_sets_a_ninety_day_expiry_without_touching_suitability(self):
        """Advancing accreditation leaves the suitability dimension alone.

        PRD: "The server stamps `accreditation_verified_at` with the current
        logical instant and sets `accreditation_expires_at` to ninety days after
        it; a verification is good for that ninety-day window and no longer."

        Design: Difficulty/non_linear_state_machine/investor_accreditation_and_suitability_independent_dimensions
        """
        deal = setup_funding_with_investor_a()

        investor = read_investor(deal["investor_a"]["id"])
        assert investor["accreditation_status"] == "VERIFIED"
        assert investor["accreditation_verified_at"] == "2026-08-20T00:00:00.000Z"
        assert investor["accreditation_expires_at"] == "2026-11-18T00:00:00.000Z"
        assert investor["suitability_status"] == "APPROVED"
        assert investor["suitability_cap_cents"] == 359_340_659

    def test_lapsing_accreditation_leaves_the_approved_cap_byte_identical(self):
        """The two dimensions are not a single linear chain.

        PRD: "The same officer records a lapse, moving `VERIFIED → EXPIRED`, but
        only once the logical clock has reached or passed
        `accreditation_expires_at` — a live verification cannot be lapsed early —
        and the lapse leaves both `suitability_status` and `suitability_cap_cents`
        untouched."

        Design: Difficulty/non_linear_state_machine/investor_accreditation_and_suitability_independent_dimensions
        """
        deal = setup_funding_with_investor_a()
        set_clock("2026-11-19T00:00:00Z")

        investor = lapse_accreditation(deal["investor_a"]["id"])

        assert investor["accreditation_status"] == "EXPIRED"
        assert investor["suitability_status"] == "APPROVED"
        assert investor["suitability_cap_cents"] == 359_340_659
        assert investor["suitability_offering_id"] == deal["offering"]["id"]
        assert investor["accreditation_expires_at"] == "2026-11-18T00:00:00.000Z"

    def test_each_dimension_advances_without_disturbing_the_other(self):
        """Verification does not review, and review does not verify.

        PRD: "Accreditation runs `UNVERIFIED → VERIFIED → EXPIRED`. Suitability
        runs `NOT_REVIEWED → APPROVED` or `NOT_REVIEWED → DECLINED`. Advancing one
        dimension never touches the other: verifying accreditation leaves
        `suitability_status` exactly where it was, and a suitability review leaves
        `accreditation_status` exactly where it was."

        Design: Difficulty/non_linear_state_machine/investor_accreditation_and_suitability_independent_dimensions
        """
        deal = setup_offering_effective()
        investor = create_investor(**INVESTOR_A)
        assert investor["accreditation_status"] == "UNVERIFIED"
        assert investor["suitability_status"] == "NOT_REVIEWED"

        verified = verify_accreditation(investor["id"], "NW-STMT-A-2026")
        assert verified["accreditation_status"] == "VERIFIED"
        assert verified["suitability_status"] == "NOT_REVIEWED"
        assert verified["suitability_offering_id"] is None

        reviewed = review_suitability(investor["id"], deal["offering"]["id"])
        assert reviewed["suitability_status"] == "APPROVED"
        assert reviewed["suitability_cap_cents"] == 359_340_659
        assert reviewed["accreditation_status"] == "VERIFIED"
        assert (
            reviewed["accreditation_expires_at"] == verified["accreditation_expires_at"]
        )
