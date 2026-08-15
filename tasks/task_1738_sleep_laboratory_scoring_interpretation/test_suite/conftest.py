"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def sleep_technologist_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["sleep_technologist_headers"]


@pytest.fixture
def scorer_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["scorer_headers"]


@pytest.fixture
def physician_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["physician_headers"]


@pytest.fixture
def dme_coordinator_headers():
    return TEST_USERS["dme_coordinator_headers"]


@pytest.fixture
def lab_director_headers():
    return TEST_USERS["lab_director_headers"]
