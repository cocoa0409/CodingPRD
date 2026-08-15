"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def warranty_admin_headers():
    return TEST_USERS["warranty_admin_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def technician_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["technician_headers"]


@pytest.fixture
def fleet_manager_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["fleet_manager_headers"]
