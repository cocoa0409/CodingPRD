"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def monitoring_agent_headers():
    return TEST_USERS["monitoring_agent_headers"]


@pytest.fixture
def device_hub_headers():
    return TEST_USERS["device_hub_headers"]


@pytest.fixture
def caregiver_headers():
    return TEST_USERS["caregiver_headers"]


@pytest.fixture
def senior_headers():
    return TEST_USERS["senior_headers"]


@pytest.fixture
def installer_headers():
    return TEST_USERS["installer_headers"]
