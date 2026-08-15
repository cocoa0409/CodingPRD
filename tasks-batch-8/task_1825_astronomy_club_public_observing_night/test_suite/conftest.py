"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def club_officer_headers():
    return TEST_USERS["club_officer_headers"]


@pytest.fixture
def event_coordinator_headers():
    return TEST_USERS["event_coordinator_headers"]


@pytest.fixture
def equipment_chair_headers():
    return TEST_USERS["equipment_chair_headers"]


@pytest.fixture
def member_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["member_headers"]
