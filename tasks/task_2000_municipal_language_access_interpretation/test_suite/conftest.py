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
    return TEST_USERS["officer_headers"]


@pytest.fixture
def liaison_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["liaison_headers"]


@pytest.fixture
def interpreter_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["interpreter_headers"]


@pytest.fixture
def reviewer_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["reviewer_headers"]
