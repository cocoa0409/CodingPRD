"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def member_headers():
    """Shared Member headers — only safe for tests that do not exercise ownership."""
    return TEST_USERS["member_headers"]


@pytest.fixture
def moderator_headers():
    """Shared GroupModerator headers — fallback for non-ownership tests only."""
    return TEST_USERS["moderator_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
