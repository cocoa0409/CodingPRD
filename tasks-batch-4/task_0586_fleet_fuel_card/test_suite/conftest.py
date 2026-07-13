"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import NO_AUTH_HEADERS, TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def merchant_headers():
    return TEST_USERS["merchant_headers"]


@pytest.fixture
def fraud_analyst_headers():
    return TEST_USERS["fraud_analyst_headers"]


@pytest.fixture
def telematics_gateway_headers():
    return TEST_USERS["telematics_gateway_headers"]


@pytest.fixture
def fleet_manager_headers():
    return TEST_USERS["fleet_manager_headers"]


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
