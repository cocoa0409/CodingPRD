"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def regional_manager_headers():
    return TEST_USERS["regional_manager_headers"]


@pytest.fixture
def property_manager_headers():
    return TEST_USERS["property_manager_headers"]


@pytest.fixture
def turn_coordinator_headers():
    return TEST_USERS["turn_coordinator_headers"]


@pytest.fixture
def vendor_headers():
    return TEST_USERS["vendor_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
