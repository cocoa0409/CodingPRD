"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def developer_headers():
    return TEST_USERS["housing_developer_headers"]


@pytest.fixture
def marketing_headers():
    return TEST_USERS["marketing_coordinator_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["application_clerk_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def lottery_admin_headers():
    return TEST_USERS["lottery_administrator_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["funding_agency_auditor_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
