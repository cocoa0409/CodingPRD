"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def president_headers():
    return TEST_USERS["president_headers"]


@pytest.fixture
def treasurer_headers():
    return TEST_USERS["treasurer_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def librarian_headers():
    return TEST_USERS["librarian_headers"]


@pytest.fixture
def member_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["member_headers"]
