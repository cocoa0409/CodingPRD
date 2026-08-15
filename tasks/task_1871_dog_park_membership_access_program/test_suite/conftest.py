"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def park_admin_headers():
    return TEST_USERS["park_admin_headers"]


@pytest.fixture
def member_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["member_headers"]


@pytest.fixture
def steward_headers():
    # Shared fallback: only safe for tests that do not exercise the steward
    # gate with a real flagged member.
    return TEST_USERS["steward_headers"]
