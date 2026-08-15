"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def firm_admin_headers():
    return TEST_USERS["firm_admin_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def agent_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["agent_headers"]


@pytest.fixture
def business_manager_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["business_manager_headers"]


@pytest.fixture
def publicist_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["publicist_headers"]


@pytest.fixture
def artist_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["artist_headers"]
