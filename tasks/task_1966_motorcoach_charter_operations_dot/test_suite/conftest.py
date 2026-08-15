"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def quote_agent_headers():
    return TEST_USERS["quote_agent_headers"]


@pytest.fixture
def dispatch_manager_headers():
    return TEST_USERS["dispatch_manager_headers"]


@pytest.fixture
def fleet_manager_headers():
    return TEST_USERS["fleet_manager_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
