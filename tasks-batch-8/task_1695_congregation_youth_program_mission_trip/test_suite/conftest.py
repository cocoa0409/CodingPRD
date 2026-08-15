"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def leader_headers():
    return TEST_USERS["leader_headers"]


@pytest.fixture
def treasurer_headers():
    return TEST_USERS["treasurer_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def guardian_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["guardian_headers"]


@pytest.fixture
def chaperone_headers():
    # Shared fallback: only safe for role-denial probes (no real record).
    return TEST_USERS["chaperone_headers"]
