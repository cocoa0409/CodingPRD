"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def am_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["am_headers"]


@pytest.fixture
def bk_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["bk_headers"]


@pytest.fixture
def lc_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["lc_headers"]
