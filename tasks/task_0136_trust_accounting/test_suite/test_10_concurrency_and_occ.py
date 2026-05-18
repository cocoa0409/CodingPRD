"""Optimistic concurrency control and race scenarios — PRD §2.5, §3.4, §3.5."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_asset,
    api_client,
    assert_exactly_one_succeeds,
    patch_trust_payload,
    re_get_trust,
    run_race,
    setup_active_trust,
    setup_active_trust_with_approved_income_distribution,
    setup_active_trust_with_principal,
    setup_active_trust_with_proposed_income_distribution,
    setup_draft_trust,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# OCC version mismatch — PRD §2.5
# ===========================================================================
class TestOptimisticConcurrency:

    def test_patch_with_stale_version_rejected(self, api):
        """PRD §2.5: "When the supplied version does not match, the
        server rejects the request with ERR_VERSION_MISMATCH and an
        HTTP 409 status."

        Claim: PATCHing with a stale version -> ERR_VERSION_MISMATCH.
        """
        scenario = setup_draft_trust()
        stale_version = scenario.trust["version"]
        # First successful patch increments version.
        first = api.patch_trust(
            scenario.trust["id"],
            patch_trust_payload(
                name="Renamed Once",
                version=stale_version,
            ),
            scenario.grantor_headers,
        )
        validate_success(first, 200)
        # Now patch with the OLD version.
        resp = api.patch_trust(
            scenario.trust["id"],
            patch_trust_payload(
                name="Renamed Again",
                version=stale_version,
            ),
            scenario.grantor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_MISMATCH.value)

    def test_patch_with_current_version_succeeds(self, api):
        """PRD §2.5: "When the supplied version matches the
        resource's current version, the mutation is applied and the
        resource's version is incremented."

        Claim: PATCH with the current version returns 200 and
        increments version by 1.
        """
        scenario = setup_draft_trust()
        old_version = scenario.trust["version"]
        resp = api.patch_trust(
            scenario.trust["id"],
            patch_trust_payload(
                name="Patched Name", version=old_version,
            ),
            scenario.grantor_headers,
        )
        trust = validate_success(resp, 200)
        assert trust["version"] == old_version + 1


# ===========================================================================
# Race: two trustees racing to approve the same PROPOSED Distribution
# — PRD §3.4 explicit guarantee.
# ===========================================================================
class TestApproveRace:

    def test_two_approvers_race_exactly_one_wins(self, api):
        """PRD §3.4: "Two trustees racing to approve the same
        PROPOSED Distribution serialize on Distribution.status:
        exactly one succeeds, and the second observes that the
        distribution is no longer PROPOSED and is rejected with
        ERR_INVALID_STATE."

        Claim: launching two concurrent approves from two distinct
        trustees on the same PROPOSED distribution results in
        exactly one success and one ERR_INVALID_STATE (the loser).
        """
        scenario, dist = (
            setup_active_trust_with_proposed_income_distribution(
                income_amount=5_000.00,
                distribution_income=500.00,
                proposer="grantor",  # so any trustee can approve
                num_trustees=2,
            )
        )
        # We need TWO distinct approver headers, both different from
        # the proposer. Both trustees on the scenario qualify.
        from test_helpers import add_trustee
        # Just use the two trustees set up by num_trustees=2.
        h1 = scenario.primary_trustee_headers
        h2 = scenario.second_trustee_headers
        assert h1["X-User-ID"] != h2["X-User-ID"]

        trust_id = scenario.trust["id"]
        dist_id = dist["id"]
        results = run_race(
            lambda: api.approve_distribution(trust_id, dist_id, h1),
            lambda: api.approve_distribution(trust_id, dist_id, h2),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser_resp = outcome["failures"][0]
        # PRD §3.4 names the loser code as ERR_INVALID_STATE.
        validate_error(
            loser_resp, ApiErrorId.ERR_INVALID_STATE.value,
        )


# ===========================================================================
# Race: two execute on different APPROVED distributions sharing balance
# — PRD §3.4 explicit guarantee.
# ===========================================================================
class TestExecuteBalanceRace:

    def test_two_principal_executions_race_loser_sees_insufficient(
        self, api,
    ):
        """PRD §3.4: "Two executions racing on two different APPROVED
        distributions that individually fit the Trust's
        principal_balance but together do not serialize as
        first-writer-wins on the principal debit: the first
        execution succeeds, and the second observes the reduced
        principal_balance and is rejected with
        ERR_INSUFFICIENT_PRINCIPAL."

        Claim: two concurrent executes, each individually fitting
        but together not -> one succeeds, the other gets
        ERR_INSUFFICIENT_PRINCIPAL.
        """
        # principal_balance = 100; each distribution is 70 principal.
        scenario = setup_active_trust_with_principal(
            principal_amount=100.00, num_trustees=2,
        )
        # Propose two distributions of $70 each (any one fits, both
        # don't). We need TWO distinct beneficiaries to keep things
        # clean and avoid funky balance interactions in some
        # implementations.
        from test_helpers import (
            add_beneficiary, approve_distribution,
            propose_distribution,
        )
        b2 = add_beneficiary(
            scenario.trust, scenario.grantor_headers,
            full_name="B2", relation_class="CHILD",
            distribution_tier="TIER_2",
        )
        d1 = propose_distribution(
            scenario.trust, scenario.beneficiary,
            scenario.primary_trustee_headers,
            amount_principal=70.00,
            distribution_type="DISCRETIONARY",
        )
        d2 = propose_distribution(
            scenario.trust, b2,
            scenario.primary_trustee_headers,
            amount_principal=70.00,
            distribution_type="DISCRETIONARY",
        )
        d1 = approve_distribution(
            scenario.trust, d1, scenario.second_trustee_headers,
        )
        d2 = approve_distribution(
            scenario.trust, d2, scenario.second_trustee_headers,
        )

        trust_id = scenario.trust["id"]
        h = scenario.second_trustee_headers
        results = run_race(
            lambda: api.execute_distribution(trust_id, d1["id"], h),
            lambda: api.execute_distribution(trust_id, d2["id"], h),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser_resp = outcome["failures"][0]
        validate_error(
            loser_resp, ApiErrorId.ERR_INSUFFICIENT_PRINCIPAL.value,
        )


# ===========================================================================
# Race: amend twice — PRD §3.5 explicit guarantee.
# ===========================================================================
class TestAmendRace:

    def test_two_amend_requests_serialize(self, api):
        """PRD §3.5: "Two amend requests on the same CLOSED TaxYear
        serialize on TaxYear.status from CLOSED to AMENDED: exactly
        one amendment cycle starts, and the second sees status
        AMENDED and is rejected with ERR_INVALID_STATE."

        Claim: two concurrent amend calls on the same CLOSED year
        -> one succeeds, one returns ERR_INVALID_STATE.
        """
        from test_helpers import (
            TEST_USERS, setup_closed_tax_year,
        )
        scenario = setup_closed_tax_year(income_amount=1_000.00)
        h = TEST_USERS["tax_preparer_headers"]
        trust_id = scenario.trust["id"]
        ty_id = scenario.tax_year["id"]
        results = run_race(
            lambda: api.amend_tax_year(trust_id, ty_id, h),
            lambda: api.amend_tax_year(trust_id, ty_id, h),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser_resp = outcome["failures"][0]
        validate_error(
            loser_resp, ApiErrorId.ERR_INVALID_STATE.value,
        )
