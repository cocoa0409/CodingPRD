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
def state_program_manager_headers():
    return TEST_USERS["state_program_manager_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def carrier_manager_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["carrier_manager_headers"]


@pytest.fixture
def safety_data_feed_headers():
    return TEST_USERS["safety_data_feed_headers"]


@pytest.fixture
def telematics_gateway_headers():
    return TEST_USERS["telematics_gateway_headers"]


@pytest.fixture
def finance_admin_headers():
    return TEST_USERS["finance_admin_headers"]
