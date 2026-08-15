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
def trust_agent_headers():
    return TEST_USERS["trust_agent_headers"]


@pytest.fixture
def appeals_officer_headers():
    return TEST_USERS["appeals_officer_headers"]


@pytest.fixture
def sponsor_headers():
    return TEST_USERS["sponsor_headers"]


@pytest.fixture
def creator_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["creator_headers"]


@pytest.fixture
def moderator_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["moderator_headers"]
