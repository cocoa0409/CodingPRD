"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def operations_manager_headers():
    return TEST_USERS["operations_manager_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def entry_supervisor_headers():
    # Shared fallback: only safe for tests that do not exercise identity.
    return TEST_USERS["entry_supervisor_headers"]


@pytest.fixture
def attendant_headers():
    # Shared fallback: only safe for tests that do not exercise identity.
    return TEST_USERS["attendant_headers"]


@pytest.fixture
def rescue_team_lead_headers():
    # Shared fallback: only safe for tests that do not exercise identity.
    return TEST_USERS["rescue_team_lead_headers"]


@pytest.fixture
def safety_officer_headers():
    # Shared fallback: only safe for tests that do not exercise identity.
    return TEST_USERS["safety_officer_headers"]
