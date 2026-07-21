"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def collections_agent_headers():
    return TEST_USERS["collections_agent_headers"]


@pytest.fixture
def collections_manager_headers():
    return TEST_USERS["collections_manager_headers"]


@pytest.fixture
def renter_headers():
    return TEST_USERS["renter_headers"]


@pytest.fixture
def property_manager_headers():
    return TEST_USERS["property_manager_headers"]
