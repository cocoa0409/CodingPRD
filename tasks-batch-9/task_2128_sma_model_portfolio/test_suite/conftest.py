"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def portfolio_manager_headers():
    return TEST_USERS["portfolio_manager_headers"]


@pytest.fixture
def portfolio_manager_2_headers():
    return TEST_USERS["portfolio_manager_2_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_2_headers():
    return TEST_USERS["compliance_officer_2_headers"]


@pytest.fixture
def billing_officer_headers():
    return TEST_USERS["billing_officer_headers"]


@pytest.fixture
def sponsor_operator_headers():
    """Fallback SponsorOperator identity — never for an ownership-gated call."""
    return TEST_USERS["sponsor_operator_headers"]
