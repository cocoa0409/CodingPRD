"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import NO_AUTH_HEADERS, TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def property_manager_headers():
    return TEST_USERS["property_manager_headers"]


@pytest.fixture
def property_manager_2_headers():
    return TEST_USERS["property_manager_2_headers"]


@pytest.fixture
def leasing_agent_headers():
    return TEST_USERS["leasing_agent_headers"]


@pytest.fixture
def tenant_headers():
    return TEST_USERS["tenant_headers"]


@pytest.fixture
def system_ops_headers():
    return TEST_USERS["system_ops_headers"]


@pytest.fixture
def no_auth_headers():
    return dict(NO_AUTH_HEADERS)
