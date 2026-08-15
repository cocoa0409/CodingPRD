"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def meet_director_headers():
    return TEST_USERS["meet_director_headers"]


@pytest.fixture
def team_coach_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["team_coach_headers"]


@pytest.fixture
def timing_operator_headers():
    return TEST_USERS["timing_operator_headers"]


@pytest.fixture
def deck_official_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["deck_official_headers"]


@pytest.fixture
def meet_referee_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["meet_referee_headers"]


@pytest.fixture
def records_officer_headers():
    return TEST_USERS["records_officer_headers"]
