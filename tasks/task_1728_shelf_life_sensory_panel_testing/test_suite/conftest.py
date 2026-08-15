"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def lab_director_headers():
    return TEST_USERS["lab_director_headers"]


@pytest.fixture
def scientist_headers():
    return TEST_USERS["scientist_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def qa_headers():
    return TEST_USERS["qa_headers"]


@pytest.fixture
def panelist_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["panelist_headers"]


@pytest.fixture
def client_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["client_headers"]
