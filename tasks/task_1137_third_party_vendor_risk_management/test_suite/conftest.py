"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def vrm_headers():
    return TEST_USERS["vrm_headers"]


@pytest.fixture
def risk_officer_headers():
    return TEST_USERS["risk_officer_headers"]


@pytest.fixture
def business_owner_headers():
    return TEST_USERS["business_owner_headers"]


@pytest.fixture
def internal_auditor_headers():
    return TEST_USERS["internal_auditor_headers"]


@pytest.fixture
def compliance_director_headers():
    return TEST_USERS["compliance_director_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
