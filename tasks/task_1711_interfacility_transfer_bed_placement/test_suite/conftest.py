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
def any_headers():
    return TEST_USERS["any_headers"]


@pytest.fixture
def sending_physician_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["sending_physician_headers"]


@pytest.fixture
def receiving_physician_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["receiving_physician_headers"]


@pytest.fixture
def bed_manager_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["bed_manager_headers"]


@pytest.fixture
def quality_reviewer_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["quality_reviewer_headers"]
