"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def ops_headers() -> dict:
    """LeagueLicensingManager."""
    return TEST_USERS["league_licensing_manager_headers"]


@pytest.fixture
def compliance_headers() -> dict:
    """MarkComplianceOfficer."""
    return TEST_USERS["mark_compliance_officer_headers"]


@pytest.fixture
def finance_headers() -> dict:
    """FinanceController."""
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def finance_alt_headers() -> dict:
    """A second FinanceController, for separation-of-duties paths."""
    return TEST_USERS["finance_controller_alt_headers"]


@pytest.fixture
def auditor_headers() -> dict:
    """RoyaltyAuditor."""
    return TEST_USERS["royalty_auditor_headers"]


@pytest.fixture
def auditor_alt_headers() -> dict:
    """A second RoyaltyAuditor."""
    return TEST_USERS["royalty_auditor_alt_headers"]
