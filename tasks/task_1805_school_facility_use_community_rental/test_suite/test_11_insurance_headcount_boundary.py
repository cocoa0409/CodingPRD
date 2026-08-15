"""Insurance headcount tiers: the tier-2 lower bound at headcount 100 is
inclusive — 99 passes under a tier-1 certificate, 100 demands tier 2
(PRD §3.3, §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    make_booking_env, make_under_review_request, approve,
    make_draft_request, submit_request, begin_review,
    make_insurance,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

DIRECTOR = TEST_USERS["director_headers"]

# Per-occurrence 150000000 sits between the tier-1 floor (100000000) and the
# tier-2 floor (200000000); aggregate 400000000 meets both aggregate floors.
MID_CERT = {"per_occurrence_limit_cents": 150000000,
            "aggregate_limit_cents": 400000000}
FULL_CERT = {"per_occurrence_limit_cents": 200000000,
             "aggregate_limit_cents": 400000000}


class TestInsuranceHeadcountTier100Boundary:
    def test_headcount_99_approves_with_tier1_certificate(self, api):
        """PRD §3.3: "How much insurance is enough depends on crowd size, in three
        tiers with inclusive lower bounds. A headcount below 100 requires a
        per-occurrence limit of at least 100000000 cents and an aggregate limit
        of at least 200000000 cents."

        Design: Difficulty/boundary_precision_check/insurance_headcount_tier_100_boundary
        """
        env = make_booking_env(insurance_overrides=MID_CERT)
        req = make_under_review_request(
            env, event_title="Small Gala", headcount_estimate=99,
            starts_at="2026-12-05T01:00:00Z", ends_at="2026-12-05T04:00:00Z")
        # 150000000 >= 100000000 tier-1 floor: the gate passes.
        permit = approve(req["id"], req["version"])
        assert permit["lifecycle_status"] == "ISSUED"
        assert permit["renter_org_id"] == env["org"]["id"]

    def test_headcount_100_belongs_to_tier2_and_rejects(self, api):
        """PRD §3.3: "A headcount of at least 100 but below 500 requires at least
        200000000 per occurrence and at least 400000000 in aggregate."
        PRD §3.4: "The insurance gate of §3.3 must pass for a non-`INTERNAL`
        renter (else `ERR_INSURANCE_INSUFFICIENT`)."

        Design: Difficulty/boundary_precision_check/insurance_headcount_tier_100_boundary
        """
        # Submit under a full tier-2 certificate, then swap in the 150000000
        # certificate while the request still sits SUBMITTED (the revocation
        # cascade only sends UNDER_REVIEW requests back to REVISION_REQUESTED),
        # so the shortfall surfaces at the approval gate itself.
        env = make_booking_env(insurance_overrides=FULL_CERT)
        req = make_draft_request(
            env, event_title="Bigger Gala", headcount_estimate=100,
            starts_at="2026-12-12T01:00:00Z", ends_at="2026-12-12T04:00:00Z")
        submit_request(env, req["id"])
        validate_success(api.revoke_insurance_certificate(
            env["cert"]["id"], {"reason": "Replaced by thinner policy"}, DIRECTOR))
        make_insurance(env["org"]["id"], insurer_name="Lean Cover", **MID_CERT)
        reviewed = begin_review(req["id"])

        res = api.approve_request(
            req["id"], {"expected_request_version": reviewed["version"]}, DIRECTOR)
        validate_error(res, ApiErrorId.ERR_INSURANCE_INSUFFICIENT)

        after = validate_success(api.get_request(req["id"], DIRECTOR))
        assert after["request_status"] == "UNDER_REVIEW"
        permits = validate_success(api.list_request_permits(req["id"], DIRECTOR))
        assert permits == [], "no Permit created by the rejected approval"
