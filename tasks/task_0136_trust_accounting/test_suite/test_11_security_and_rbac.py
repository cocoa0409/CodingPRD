"""RBAC and ownership filtering — PRD §2.1, §3.7."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_beneficiary,
    api_client,
    create_transaction_payload,
    iso_instant_utc,
    make_beneficiary_headers,
    setup_active_trust,
    setup_active_trust_with_income,
    setup_closed_tax_year,
    setup_draft_trust,
    list_k1s_for_year,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Beneficiary cannot perform mutating operations — PRD §2.1, §4
# ===========================================================================
class TestRoleExclusivity:

    def test_beneficiary_cannot_record_transaction(self, api):
        """PRD §4 endpoint table: "POST /trusts/{trustId}/transactions
        ... Authorized Role(s): Trustee".

        Claim: Beneficiary attempting to record a transaction ->
        ERR_FORBIDDEN.
        """
        scenario = setup_active_trust()
        # Use the actual beneficiary headers (entity-backed; PRD
        # §2.1).
        b_headers = make_beneficiary_headers(
            scenario.beneficiary["id"],
        )
        resp = api.create_transaction(
            scenario.trust["id"],
            create_transaction_payload(
                amount=10.00,
                transaction_date=iso_instant_utc(2026, 6, 1),
            ),
            b_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_tax_preparer_cannot_create_trust(self, api):
        """PRD §4 endpoint table: "POST /trusts ... Authorized
        Role(s): Grantor". PRD §2.1: "If the authenticated role is
        not permitted to invoke the requested endpoint, the server
        rejects the request with ERR_FORBIDDEN."

        Claim: TaxPreparer cannot POST /trusts -> ERR_FORBIDDEN.
        """
        from test_helpers import create_trust_payload
        resp = api.create_trust(
            create_trust_payload(),
            TEST_USERS["tax_preparer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_grantor_cannot_approve_distribution(self, api):
        """PRD §4 endpoint table: "POST
        /trusts/{trustId}/distributions/{distributionId}/approve ...
        Authorized Role(s): Trustee".

        Claim: Grantor attempting approve -> ERR_FORBIDDEN.
        """
        from test_helpers import (
            setup_active_trust_with_proposed_income_distribution,
        )
        scenario, dist = (
            setup_active_trust_with_proposed_income_distribution(
                income_amount=5_000.00,
                distribution_income=500.00,
                proposer="primary_trustee",
            )
        )
        resp = api.approve_distribution(
            scenario.trust["id"], dist["id"],
            scenario.grantor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Beneficiary scope filtering — PRD §3.7
# ===========================================================================
class TestBeneficiaryScope:

    def test_beneficiary_can_only_read_own_record(self, api):
        """PRD §2.1: "Ownership filtering on Beneficiary-scoped reads
        compares the resource's beneficiary_id (or, for the
        Beneficiary record itself, its id) to X-User-ID."

        Claim: a Beneficiary cannot read a different Beneficiary's
        record -> ERR_FORBIDDEN.
        """
        scenario = setup_active_trust()
        # Second beneficiary under the same trust.
        b2 = add_beneficiary(
            scenario.trust, scenario.grantor_headers,
            full_name="Other Beneficiary",
            relation_class="CHILD",
            distribution_tier="TIER_2",
        )
        # First beneficiary tries to read second beneficiary.
        first_headers = make_beneficiary_headers(
            scenario.beneficiary["id"],
        )
        resp = api.get_beneficiary(
            scenario.trust["id"], b2["id"], first_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_beneficiary_can_read_own_k1(self, api):
        """PRD §3.7: "A direct read of a single K-1 by a Beneficiary
        is permitted only when the K-1's beneficiary_id equals
        X-User-ID; otherwise the request is rejected with
        ERR_FORBIDDEN."

        Claim: a Beneficiary may read their own ISSUED K-1 directly.
        """
        scenario = setup_closed_tax_year(income_amount=2_000.00)
        # Find this beneficiary's K-1.
        k1s = list_k1s_for_year(
            scenario.trust, scenario.tax_year,
            params={"beneficiary_id": scenario.beneficiary["id"]},
        )
        own = [
            k for k in k1s
            if k["beneficiary_id"] == scenario.beneficiary["id"]
            and k["status"] == "ISSUED"
        ]
        assert own, (
            f"Expected an ISSUED K-1 for the beneficiary; got {k1s}"
        )
        b_headers = make_beneficiary_headers(
            scenario.beneficiary["id"],
        )
        resp = api.get_k1(
            scenario.trust["id"], scenario.tax_year["id"],
            own[0]["id"], b_headers,
        )
        k1 = validate_success(resp, 200)
        assert k1["beneficiary_id"] == scenario.beneficiary["id"]

    def test_beneficiary_cannot_read_other_k1(self, api):
        """PRD §3.7: "A direct read of a single K-1 by a Beneficiary
        is permitted only when the K-1's beneficiary_id equals
        X-User-ID; otherwise the request is rejected with
        ERR_FORBIDDEN."

        Claim: Beneficiary trying to read another beneficiary's
        K-1 directly -> ERR_FORBIDDEN.
        """
        scenario = setup_closed_tax_year(income_amount=2_000.00)
        # Add a second beneficiary BEFORE amending so its K-1
        # exists after the year is re-amended-and-closed.
        b2 = add_beneficiary(
            scenario.trust, scenario.grantor_headers,
            full_name="Sibling", relation_class="CHILD",
            distribution_tier="TIER_2",
        )
        # Re-open the year to issue a K-1 for b2.
        from test_helpers import amend_tax_year, finalize_tax_year
        scenario.tax_year = amend_tax_year(
            scenario.trust, scenario.tax_year,
        )
        scenario.tax_year = finalize_tax_year(
            scenario.trust, scenario.tax_year,
        )
        # Find b2's ISSUED K-1.
        k1s = list_k1s_for_year(
            scenario.trust, scenario.tax_year,
            params={"beneficiary_id": b2["id"]},
        )
        b2_issued = [
            k for k in k1s
            if k["beneficiary_id"] == b2["id"] and k["status"] == "ISSUED"
        ]
        assert b2_issued, (
            f"Expected an ISSUED K-1 for b2; got {k1s}"
        )
        # First beneficiary tries to read b2's K-1.
        b_headers = make_beneficiary_headers(
            scenario.beneficiary["id"],
        )
        resp = api.get_k1(
            scenario.trust["id"], scenario.tax_year["id"],
            b2_issued[0]["id"], b_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
