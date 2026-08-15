"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def officer_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["officer_headers"]


@pytest.fixture
def captain_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["captain_headers"]


@pytest.fixture
def member_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["member_headers"]
