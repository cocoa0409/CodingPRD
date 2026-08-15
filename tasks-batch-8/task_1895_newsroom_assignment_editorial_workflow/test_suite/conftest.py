"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def news_director_headers():
    return TEST_USERS["news_director_headers"]


@pytest.fixture
def reporter_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["reporter_headers"]


@pytest.fixture
def assignment_editor_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["assignment_editor_headers"]


@pytest.fixture
def managing_editor_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["managing_editor_headers"]
