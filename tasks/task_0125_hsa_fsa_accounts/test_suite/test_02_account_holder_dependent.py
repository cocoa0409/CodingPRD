"""AccountHolder and Dependent CRUD — PRD §3.1.

Coverage targets:
- AccountHolder creation field validation (ssn_last4 must be 4 digits,
  tax_filing_status enum).
- Dependent creation begins in ACTIVE.
- Dependent deactivation transitions to INACTIVE and persists.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_account_holder,
    assert_dependent,
    create_account_holder,
    create_account_holder_payload,
    create_dependent,
    create_dependent_payload,
    deactivate_dependent,
    validate_error,
    validate_success,
)


# ===========================================================================
# AccountHolder creation — PRD §3.1
# ===========================================================================
class TestAccountHolderCreate:

    def test_create_account_holder_returns_holder(
        self, api, plan_admin_headers,
    ):
        """PRD §3.1: "Creating an account holder accepts the holder's
        legal full_name, the last four digits of their Social Security
        number (ssn_last4, which must be exactly four numeric digits;
        non-conforming values are rejected with ERR_BAD_REQUEST), their
        tax_filing_status ... and their birth_date."

        Claim: a valid POST /account-holders returns 201 with the
        AccountHolder shape (PRD §2.4 mutable resource: id +
        created_at + updated_at + version).
        """
        payload = create_account_holder_payload()
        resp = api.create_account_holder(payload, plan_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_account_holder(data)
        # Persisted fields equal what we sent.
        assert data["full_name"] == payload["full_name"]
        assert data["ssn_last4"] == payload["ssn_last4"]
        assert data["tax_filing_status"] == payload["tax_filing_status"]

    @pytest.mark.parametrize(
        "bad_ssn",
        ["123", "12345", "abcd", "12 4", ""],
    )
    def test_ssn_last4_must_be_exactly_four_digits(
        self, api, plan_admin_headers, bad_ssn,
    ):
        """PRD §3.1: "ssn_last4, which must be exactly four numeric
        digits; non-conforming values are rejected with
        ERR_BAD_REQUEST".

        Claim: non-conforming ssn_last4 -> ERR_BAD_REQUEST.
        """
        payload = create_account_holder_payload(ssn_last4=bad_ssn)
        resp = api.create_account_holder(payload, plan_admin_headers)
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)

    @pytest.mark.parametrize(
        "filing_status",
        ["SINGLE", "MARRIED_JOINT", "MARRIED_SEPARATE", "HEAD_OF_HOUSEHOLD"],
    )
    def test_create_account_holder_with_each_filing_status(
        self, api, plan_admin_headers, filing_status,
    ):
        """PRD §3.1: "their tax_filing_status (one of SINGLE,
        MARRIED_JOINT, MARRIED_SEPARATE, or HEAD_OF_HOUSEHOLD)".

        Claim: each of the four filing statuses is accepted.
        """
        payload = create_account_holder_payload(
            tax_filing_status=filing_status,
        )
        resp = api.create_account_holder(payload, plan_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["tax_filing_status"] == filing_status

    def test_account_holder_version_starts_at_one(
        self, api, plan_admin_headers,
    ):
        """PRD §2.4: "version is an integer that starts at 1 and is
        incremented by exactly 1 on every mutation".

        Claim: a freshly created AccountHolder has version == 1.
        """
        resp = api.create_account_holder(
            create_account_holder_payload(), plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["version"] == 1


# ===========================================================================
# Dependent creation — PRD §3.1
# ===========================================================================
class TestDependentCreate:

    def test_create_dependent_starts_active(
        self, api, plan_admin_headers,
    ):
        """PRD §3.1: "Dependents begin in ACTIVE status."

        Claim: a freshly added dependent has status == ACTIVE.
        """
        holder = create_account_holder()
        payload = create_dependent_payload(relationship="CHILD")
        resp = api.create_dependent(
            holder["id"], payload, plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_dependent(data)
        assert data["status"] == "ACTIVE"

    @pytest.mark.parametrize(
        "relationship",
        ["CHILD", "SPOUSE", "QUALIFYING_RELATIVE"],
    )
    def test_dependent_each_relationship_accepted(
        self, api, plan_admin_headers, relationship,
    ):
        """PRD §3.1: "Adding a dependent to an account holder accepts
        the dependent's full_name, birth_date, and relationship (one of
        CHILD, SPOUSE, or QUALIFYING_RELATIVE)."

        Claim: each of the three relationship enums is accepted.
        """
        holder = create_account_holder()
        payload = create_dependent_payload(relationship=relationship)
        resp = api.create_dependent(
            holder["id"], payload, plan_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["relationship"] == relationship


# ===========================================================================
# Dependent deactivation — PRD §3.1
# ===========================================================================
class TestDependentDeactivate:

    def test_deactivate_dependent_transitions_to_inactive(
        self, api, plan_admin_headers,
    ):
        """PRD §3.1: "A PlanAdministrator may deactivate a dependent
        (transitioning Dependent.status to INACTIVE)".

        Claim: deactivation sets Dependent.status to INACTIVE.
        """
        holder = create_account_holder()
        dep = create_dependent(account_holder=holder)
        resp = api.deactivate_dependent(dep["id"], plan_admin_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "INACTIVE"

    def test_deactivate_dependent_only_plan_administrator(
        self, api, adjudicator_headers,
    ):
        """PRD §4 table: "POST /dependents/{dependentId}/deactivate ...
        Authorized Role(s): PlanAdministrator."

        Claim: ClaimAdjudicator cannot deactivate a dependent.
        """
        holder = create_account_holder()
        dep = create_dependent(account_holder=holder)
        resp = api.deactivate_dependent(dep["id"], adjudicator_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
