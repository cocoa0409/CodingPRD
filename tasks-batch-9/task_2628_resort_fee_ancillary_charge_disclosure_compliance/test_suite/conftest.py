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
def revenue_manager_headers():
    return TEST_USERS["revenue_manager_headers"]


@pytest.fixture
def revenue_manager_2_headers():
    return TEST_USERS["revenue_manager_2_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_2_headers():
    return TEST_USERS["compliance_officer_2_headers"]


@pytest.fixture
def regulatory_liaison_headers():
    return TEST_USERS["regulatory_liaison_headers"]


@pytest.fixture
def regulatory_liaison_2_headers():
    return TEST_USERS["regulatory_liaison_2_headers"]


@pytest.fixture
def guest_services_agent_headers():
    return TEST_USERS["guest_services_agent_headers"]


@pytest.fixture
def guest_services_agent_2_headers():
    return TEST_USERS["guest_services_agent_2_headers"]


@pytest.fixture
def channel_operator_headers():
    return TEST_USERS["channel_operator_headers"]


@pytest.fixture
def guest_headers():
    return TEST_USERS["guest_headers"]
