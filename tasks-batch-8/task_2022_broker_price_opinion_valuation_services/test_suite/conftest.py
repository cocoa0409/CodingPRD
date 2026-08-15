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
def client_admin_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["client_admin_headers"]


@pytest.fixture
def operations_manager_headers():
    return TEST_USERS["operations_manager_headers"]


@pytest.fixture
def dispatch_coordinator_headers():
    return TEST_USERS["dispatch_coordinator_headers"]


@pytest.fixture
def broker_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["broker_headers"]


@pytest.fixture
def qc_reviewer_headers():
    return TEST_USERS["qc_reviewer_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]
