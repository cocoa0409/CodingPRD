"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def aid_director_headers():
    return TEST_USERS["aid_director_headers"]


@pytest.fixture
def aid_officer_headers():
    return TEST_USERS["aid_officer_headers"]


@pytest.fixture
def student_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["student_headers"]
