"""Trustees, beneficiaries, assets — PRD §3.2.

Covers:
- Trustee creation + primary-trustee replacement cascade.
- Beneficiary creation + is_skip_person computation.
- Beneficiary termination preconditions.
- Asset creation + balance cascade at funding.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    GST_GENERATION_GAP_YEARS,
    add_asset,
    add_beneficiary,
    add_trustee,
    api_client,
    assert_asset,
    assert_beneficiary,
    assert_trustee,
    create_beneficiary_payload,
    create_trustee_payload,
    iso_instant_utc,
    re_get_trust,
    setup_active_trust,
    setup_active_trust_with_income,
    setup_draft_trust,
    validate_error,
    validate_success,
)


# ===========================================================================
# Trustee — PRD §3.2
# ===========================================================================
class TestTrustees:

    def test_create_trustee_returns_trustee(self, api):
        """PRD §3.2: "A Grantor registers trustees by submitting a
        payload containing the trustee's user_id (the opaque platform
        identifier of the natural person who will act as trustee),
        their legal full_name, and a boolean is_primary flag."

        Claim: POST /trusts/{id}/trustees returns a Trustee with
        status ACTIVE and the user_id we supplied.
        """
        scenario = setup_draft_trust()
        payload = create_trustee_payload(
            user_id="trustee-user-aaaa",
            full_name="Alice",
            is_primary=True,
        )
        resp = api.create_trustee(
            scenario.trust["id"], payload, scenario.grantor_headers,
        )
        trustee = validate_success(resp, 201)
        assert_trustee(trustee)
        assert trustee["user_id"] == "trustee-user-aaaa"
        assert trustee["full_name"] == "Alice"
        assert trustee["is_primary"] is True
        assert trustee["status"] == "ACTIVE"

    def test_new_primary_demotes_prior_primary(self, api):
        """PRD §3.2: "If a new trustee is registered with is_primary
        set to true while another trustee on the same trust already
        has is_primary set to true, the prior primary is
        automatically demoted by having its is_primary flipped to
        false — this is a two-level cascade, and both trustee records
        have their version and updated_at refreshed."

        Claim: adding a second primary demotes the first
        (is_primary=false), and the first's version increments.
        """
        scenario = setup_draft_trust()
        # First primary.
        t1, _ = add_trustee(
            scenario.trust, scenario.grantor_headers,
            user_id="t1", full_name="First", is_primary=True,
        )
        t1_initial_version = t1["version"]
        # Second primary.
        add_trustee(
            scenario.trust, scenario.grantor_headers,
            user_id="t2", full_name="Second", is_primary=True,
        )
        # Re-fetch t1 — must now have is_primary=false and a bumped
        # version.
        resp = api.get_trustee(
            scenario.trust["id"], t1["id"], scenario.grantor_headers,
        )
        t1_after = validate_success(resp, 200)
        assert t1_after["is_primary"] is False
        assert t1_after["version"] == t1_initial_version + 1


# ===========================================================================
# Beneficiary — PRD §3.2 (skip-person determination)
# ===========================================================================
class TestBeneficiarySkipPerson:

    def test_grandchild_is_always_skip_person(self, api):
        """PRD §3.2: "if the relation_class is GRANDCHILD, the
        beneficiary is always a skip person."

        Claim: GRANDCHILD relation_class -> is_skip_person == true,
        regardless of birth_date.
        """
        scenario = setup_draft_trust(inception_date="2026-01-01")
        b = add_beneficiary(
            scenario.trust, scenario.grantor_headers,
            full_name="Skip GC",
            relation_class="GRANDCHILD",
            birth_date="2020-01-01",
        )
        assert b["is_skip_person"] is True

    def test_child_is_never_skip_person(self, api):
        """PRD §3.2: "For SPOUSE or CHILD, the beneficiary is never a
        skip person."

        Claim: CHILD relation_class -> is_skip_person == false.
        """
        scenario = setup_draft_trust(inception_date="2026-01-01")
        b = add_beneficiary(
            scenario.trust, scenario.grantor_headers,
            full_name="Child",
            relation_class="CHILD",
            birth_date="2000-01-01",
        )
        assert b["is_skip_person"] is False

    def test_spouse_is_never_skip_person(self, api):
        """PRD §3.2: "For SPOUSE or CHILD, the beneficiary is never a
        skip person."

        Claim: SPOUSE relation_class -> is_skip_person == false.
        """
        scenario = setup_draft_trust(inception_date="2026-01-01")
        b = add_beneficiary(
            scenario.trust, scenario.grantor_headers,
            full_name="Spouse",
            relation_class="SPOUSE",
            birth_date="1990-01-01",
        )
        assert b["is_skip_person"] is False

    def test_non_lineal_below_age_gap_not_skip(self, api):
        """PRD §3.2: "The threshold uses an at-least comparison, so an
        age difference of exactly 37.5 years qualifies as a skip
        person; 37.49 does not."

        Claim: NON_LINEAL beneficiary born 37.4986 years after
        inception_date (one day short of 37.5) -> is_skip_person ==
        false.
        """
        scenario = setup_draft_trust(inception_date="2026-01-01")
        # 37 years + 6 months - 1 day = 2063-07-01 -> ~37.4986 years.
        b = add_beneficiary(
            scenario.trust, scenario.grantor_headers,
            full_name="Just-under NL",
            relation_class="NON_LINEAL",
            birth_date="2063-07-01",
        )
        assert b["is_skip_person"] is False, (
            f"NON_LINEAL just below 37.5 years should NOT be a skip "
            f"person; got {b['is_skip_person']!r}"
        )

    def test_non_lineal_at_age_gap_is_skip(self, api):
        """PRD §3.2: "The threshold uses an at-least comparison, so an
        age difference of exactly 37.5 years qualifies as a skip
        person".

        Claim: NON_LINEAL born exactly 37.5 years (2063-07-02 after
        2026-01-01) after inception_date -> is_skip_person == true.
        """
        scenario = setup_draft_trust(inception_date="2026-01-01")
        # 2026-01-01 + 37.5 years (using day-count / 365.25) is on or
        # before 2063-07-02. PRD-difficulty index pins 2063-07-02 as
        # the >=37.5 boundary; matches "at least 37.5 years" rule.
        b = add_beneficiary(
            scenario.trust, scenario.grantor_headers,
            full_name="Exact NL",
            relation_class="NON_LINEAL",
            birth_date="2063-07-02",
        )
        assert b["is_skip_person"] is True, (
            f"NON_LINEAL at exactly 37.5 years SHOULD be a skip "
            f"person; got {b['is_skip_person']!r}"
        )


# ===========================================================================
# Beneficiary termination — PRD §3.2
# ===========================================================================
class TestBeneficiaryTermination:

    def test_terminate_beneficiary_succeeds(self, api):
        """PRD §3.2: "Terminating a beneficiary is a trustee
        operation. The transition is ACTIVE → TERMINATED".

        Claim: trustee-initiated terminate moves status ACTIVE ->
        TERMINATED.
        """
        scenario = setup_active_trust()
        resp = api.terminate_beneficiary(
            scenario.trust["id"], scenario.beneficiary["id"],
            scenario.primary_trustee_headers,
        )
        b = validate_success(resp, 200)
        assert b["status"] == "TERMINATED"

    def test_terminate_blocked_when_trust_not_active(self, api):
        """PRD §3.2: "it is rejected with ... ERR_TRUST_NOT_ACTIVE if
        the parent Trust is not in ACTIVE status."

        Claim: a DRAFT trust's beneficiary cannot be terminated ->
        ERR_TRUST_NOT_ACTIVE.
        """
        scenario = setup_draft_trust()
        # Add a primary trustee + beneficiary (no activation).
        _, trustee_headers = add_trustee(
            scenario.trust, scenario.grantor_headers, is_primary=True,
        )
        b = add_beneficiary(
            scenario.trust, scenario.grantor_headers,
            relation_class="CHILD",
        )
        resp = api.terminate_beneficiary(
            scenario.trust["id"], b["id"], trustee_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TRUST_NOT_ACTIVE.value)


# ===========================================================================
# Assets — PRD §3.2
# ===========================================================================
class TestAssets:

    def test_asset_creation_in_draft_trust(self, api):
        """PRD §3.2: "Assets may be added by either a Grantor or a
        Trustee. The request body carries a description string, an
        asset_class (CASH, EQUITY, BOND, REAL_ESTATE, or OTHER), a
        book_value in USD with two decimal places, and a
        classification of either PRINCIPAL or INCOME."

        Claim: Grantor creates an Asset under a DRAFT trust; status
        is FUNDED.
        """
        scenario = setup_draft_trust()
        asset = add_asset(
            scenario.trust,
            book_value=50_000.00,
            classification="PRINCIPAL",
            asset_class="CASH",
            description="opening principal",
            headers=scenario.grantor_headers,
        )
        assert_asset(asset)
        assert asset["status"] == "FUNDED"
        assert asset["classification"] == "PRINCIPAL"

    def test_funded_principal_asset_bumps_principal_balance_in_active(
        self, api,
    ):
        """PRD §3.2: "Adding a FUNDED asset increases the Trust's
        principal_balance by book_value when classification is
        PRINCIPAL, or its income_balance by book_value when
        classification is INCOME; the Trust's version and updated_at
        are refreshed by the cascade."

        Claim: under an ACTIVE trust, POST asset of classification
        PRINCIPAL adds book_value to Trust.principal_balance.
        """
        scenario = setup_active_trust()
        before = scenario.trust["principal_balance"]
        add_asset(
            scenario.trust,
            book_value=25_000.00,
            classification="PRINCIPAL",
            asset_class="CASH",
            headers=scenario.grantor_headers,
        )
        scenario.trust = re_get_trust(scenario.trust["id"])
        assert scenario.trust["principal_balance"] == pytest.approx(
            before + 25_000.00, abs=0.01,
        )

    def test_funded_income_asset_bumps_income_balance(self, api):
        """PRD §3.2: "Adding a FUNDED asset increases the Trust's
        principal_balance by book_value when classification is
        PRINCIPAL, or its income_balance by book_value when
        classification is INCOME".

        Claim: POST asset classification INCOME bumps income_balance.
        """
        scenario = setup_active_trust()
        before = scenario.trust["income_balance"]
        add_asset(
            scenario.trust,
            book_value=4_000.00,
            classification="INCOME",
            asset_class="CASH",
            description="accrued income",
            headers=scenario.grantor_headers,
        )
        scenario.trust = re_get_trust(scenario.trust["id"])
        assert scenario.trust["income_balance"] == pytest.approx(
            before + 4_000.00, abs=0.01,
        )
