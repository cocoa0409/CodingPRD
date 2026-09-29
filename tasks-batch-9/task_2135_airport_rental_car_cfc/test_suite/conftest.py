"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.  Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin_headers():
    """FacilityAdmin — the airport authority's property manager."""
    return TEST_USERS["facility_admin_headers"]


@pytest.fixture
def auditor_headers():
    """AuditOfficer aud-1 — the transaction-day audit authority."""
    return TEST_USERS["audit_officer_headers"]


@pytest.fixture
def auditor_2_headers():
    """A second AuditOfficer, aud-2, for segregation-of-duties scenarios."""
    return TEST_USERS["audit_officer_2_headers"]


@pytest.fixture
def treasury_headers():
    """FinanceOfficer fin-1 — the CFC trust and bond treasury."""
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def treasury_2_headers():
    """A second FinanceOfficer, fin-2, for two-signature capital draws."""
    return TEST_USERS["finance_officer_2_headers"]


@pytest.fixture
def operator_headers():
    """ConcessionaireOperator headers not bound to any registered brand.

    Only safe for calls that never reach an ownership check.
    """
    return TEST_USERS["operator_headers"]
