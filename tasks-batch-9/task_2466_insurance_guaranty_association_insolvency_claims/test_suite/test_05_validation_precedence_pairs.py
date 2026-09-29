"""Requests that break two rules at once must report the higher-ranked failure."""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_instant_equals,
    claim_payload,
    get_success_data,
    make_claims_committee_officer_headers,
    move_clock,
    read_claim,
    read_insolvency,
    setup_approved_claim,
    setup_presented_claim,
    setup_recommended_claim_with_pursuing_layer,
    validate_error,
)

ANALYST = TEST_USERS["coverage_analyst_headers"]

KESTREL = {
    "vendor_type": "ADJUSTER",
    "vendor_name": "Kestrel Claims Services",
    "settlement_authority_cents": 2_500_000,
    "hourly_rate_cents": 18_000,
    "engagement_start": "2026-08-01",
    "engagement_end": "2026-08-31",
}
LARGE_CLAIM = {"claim_number": "C-1", "gross_loss_cents": 4_500_000}
NORTHLINE_LAYER = {
    "carrier_name": "Northline Casualty",
    "policy_number": "NL-77",
    "coverage_type": "PRIMARY",
    "stated_limit_cents": 2_000_000,
}
SCREENING_USER = "user-7"


class TestClaimStateOutranksAdjusterAuthority:
    """An adjuster re-recommending above authority on a settled claim."""

    def _approved(self) -> dict:
        return setup_approved_claim(
            recommended_amount_cents=2_400_000,
            assignment_overrides=dict(KESTREL),
            claim_overrides=dict(LARGE_CLAIM),
        )

    def test_inadmissible_status_is_reported_ahead_of_the_authority_breach(self):
        """Checks are evaluated in the following priority order, and the first failing check is the
        one reported:

        Design: Difficulty/priority_pair_validation_conflict/claim_state_check_outranks_adjuster_authority_check_on_recommend
        """
        env = self._approved()
        assert env["claim"]["status"] == "APPROVED"

        response = api_client.recommend_claim(
            env["claim"]["id"],
            {
                "recommended_amount_cents": 2_600_000,
                "note": "adjuster tries to re-recommend above authority",
            },
            env["adjuster_headers"],
        )
        validate_error(response, "ERR_CLAIM_INVALID_STATE", 409)
        assert response.json()["data"]["error_id"] != "ERR_ADJUSTER_AUTHORITY_EXCEEDED", (
            "the authority breach at the lower rank must never be the reported failure"
        )

    def test_refused_recommendation_leaves_the_approved_claim_untouched(self):
        """The target claim's `status` is a declared origin state of the requested transition →
        `ERR_CLAIM_INVALID_STATE` (HTTP 409), on `POST /claims/{id}/screen`,
        `POST /claims/{id}/vendor-assignments`, `POST /claims/{id}/recommend`,
        `POST /claims/{id}/approve`, `POST /claims/{id}/referrals`,
        `POST /claims/{id}/other-insurance` and `PATCH /claims/{id}/other-insurance/{coverageId}`.

        Design: Difficulty/priority_pair_validation_conflict/claim_state_check_outranks_adjuster_authority_check_on_recommend
        """
        env = self._approved()

        within_authority = api_client.recommend_claim(
            env["claim"]["id"], {"recommended_amount_cents": 2_000_000}, env["adjuster_headers"]
        )
        validate_error(within_authority, "ERR_CLAIM_INVALID_STATE", 409)

        claim = read_claim(env["claim"]["id"])
        assert claim["status"] == "APPROVED", claim["status"]
        assert claim["recommended_amount_cents"] == 2_400_000, (
            f"the recommendation that was approved must survive, got {claim['recommended_amount_cents']}"
        )


class TestFilingDeadlineOutranksDuplicateClaim:
    """A duplicate claim number presented after the proof-of-claim deadline."""

    def test_late_duplicate_reports_the_deadline_rather_than_the_collision(self):
        """The logical-clock instant of the request is at or before the insolvency file's
        `proof_of_claim_deadline_utc`, the boundary instant itself being allowed →
        `ERR_FILING_DEADLINE_PASSED` (HTTP 422), on `POST /claims` and
        `POST /policies/{id}/premium-refunds`.

        Design: Difficulty/priority_pair_validation_conflict/filing_deadline_check_outranks_duplicate_claim_check
        """
        env = setup_presented_claim(claim_overrides=dict(LARGE_CLAIM))
        move_clock("2027-03-02T00:00:00Z")

        response = api_client.create_claim(
            claim_payload(
                env["insolvency"]["id"],
                env["policy"]["id"],
                claim_number="C-1",
                claimant_name="Ben Ortiz",
                gross_loss_cents=1_000_000,
            ),
            ANALYST,
        )
        validate_error(response, "ERR_FILING_DEADLINE_PASSED", 422)
        assert response.json()["data"]["error_id"] != "ERR_DUPLICATE_CLAIM", (
            "the collision at the lower rank must never be the reported failure"
        )

        rows = get_success_data(
            api_client.list_claims(ANALYST, params={"policy_id": env["policy"]["id"]})
        )
        assert len(rows) == 1, f"the refused filing must create nothing, got {len(rows)} claims"

    def test_at_the_boundary_instant_the_collision_becomes_the_reported_failure(self):
        """It computes `proof_of_claim_deadline_utc` as the `liquidation_order_date` advanced by 365
        calendar days, at the instant `00:00:00Z` on that date; filings at exactly that instant are
        still accepted, and only filings strictly after it are late.

        Design: Difficulty/priority_pair_validation_conflict/filing_deadline_check_outranks_duplicate_claim_check
        """
        env = setup_presented_claim(claim_overrides=dict(LARGE_CLAIM))
        insolvency = read_insolvency(env["insolvency"]["id"])
        assert_instant_equals(
            insolvency["proof_of_claim_deadline_utc"],
            "2027-03-01T00:00:00Z",
            "2026-03-01 advanced by 365 days is 2027-03-01, got "
            f"{insolvency['proof_of_claim_deadline_utc']}",
        )

        move_clock("2027-03-01T00:00:00Z")
        response = api_client.create_claim(
            claim_payload(
                env["insolvency"]["id"],
                env["policy"]["id"],
                claim_number="C-1",
                claimant_name="Ben Ortiz",
                gross_loss_cents=1_000_000,
            ),
            ANALYST,
        )
        validate_error(response, "ERR_DUPLICATE_CLAIM", 409)


class TestSegregationOfDutiesOutranksOtherInsurance:
    """An approval that is both self-approved and premature."""

    def _defective(self) -> dict:
        return setup_recommended_claim_with_pursuing_layer(
            recommended_amount_cents=1_000_000,
            analyst_user_id=SCREENING_USER,
            layer_overrides=dict(NORTHLINE_LAYER),
            assignment_overrides={**KESTREL, "settlement_authority_cents": 2_000_000},
            claim_overrides=dict(LARGE_CLAIM),
        )

    def test_self_approval_is_reported_ahead_of_the_unresolved_layer(self):
        """Those two recorded values drive the segregation-of-duties rule: an approval whose acting
        `X-User-ID` is equal to the claim's stored `screened_by_user_id` is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), because the same person may not both certify coverage
        and authorise payment.

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_check_outranks_other_insurance_exhaustion_check
        """
        env = self._defective()
        assert read_claim(env["claim"]["id"])["screened_by_user_id"] == SCREENING_USER

        response = api_client.approve_claim(
            env["claim"]["id"],
            make_claims_committee_officer_headers(SCREENING_USER),
            {"approval_note": "same person who screened it"},
        )
        validate_error(response, "ERR_SEGREGATION_OF_DUTIES", 403)
        assert response.json()["data"]["error_id"] != "ERR_OTHER_INSURANCE_NOT_EXHAUSTED", (
            "the non-duplication guard at the lower rank must never be the reported failure"
        )

        claim = read_claim(env["claim"]["id"])
        assert claim["status"] == "RECOMMENDED", claim["status"]
        assert claim["approved_by_user_id"] is None
        assert read_insolvency(env["insolvency"]["id"])["reserved_claim_cents"] == 0

    def test_a_different_officer_then_meets_the_non_duplication_guard(self):
        """Three business guards apply, in the priority order set out in the validation cascade:
        first the segregation-of-duties check, which refuses the approval with
        `ERR_SEGREGATION_OF_DUTIES` when the acting `X-User-ID` equals the claim's
        `screened_by_user_id`; then the non-duplication check, which refuses with
        `ERR_OTHER_INSURANCE_NOT_EXHAUSTED` unless every other-insurance layer on the claim has
        reached `EXHAUSTED` or `CARRIER_DENIED`; then the aggregate-cap check, which requires the
        claim's currently stored `net_payable_cents` to be at or below the line's
        `per_policy_aggregate_cap_cents` less the policy's `aggregate_paid_cents`, floored at 0, and
        refuses with `ERR_AGGREGATE_CAP_EXHAUSTED` otherwise.

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_check_outranks_other_insurance_exhaustion_check
        """
        env = self._defective()

        response = api_client.approve_claim(
            env["claim"]["id"], make_claims_committee_officer_headers("officer-9"), {}
        )
        validate_error(response, "ERR_OTHER_INSURANCE_NOT_EXHAUSTED", 409)

        claim = read_claim(env["claim"]["id"])
        assert claim["status"] == "RECOMMENDED", claim["status"]
        assert claim["approved_by_user_id"] is None
