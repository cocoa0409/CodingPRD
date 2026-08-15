"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def event_director_headers():
    return TEST_USERS["event_director_headers"]


@pytest.fixture
def team_coach_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["team_coach_headers"]


@pytest.fixture
def judge_headers():
    # Shared fallback: only safe for tests that do not exercise authorship.
    return TEST_USERS["judge_headers"]


@pytest.fixture
def head_judge_headers():
    # Shared fallback: only safe for tests that do not exercise segregation.
    return TEST_USERS["head_judge_headers"]


@pytest.fixture
def safety_judge_headers():
    # Shared fallback: only safe for tests that do not exercise applier checks.
    return TEST_USERS["safety_judge_headers"]


@pytest.fixture
def music_compliance_headers():
    return TEST_USERS["music_compliance_headers"]


@pytest.fixture
def eligibility_officer_headers():
    return TEST_USERS["eligibility_officer_headers"]


@pytest.fixture
def spectator_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["spectator_headers"]
