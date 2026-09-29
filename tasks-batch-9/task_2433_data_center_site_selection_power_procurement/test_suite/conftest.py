"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def analyst_headers() -> dict:
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def analyst_2_headers() -> dict:
    return TEST_USERS["analyst_2_headers"]


@pytest.fixture
def director_headers() -> dict:
    return TEST_USERS["director_headers"]


@pytest.fixture
def negotiator_headers() -> dict:
    return TEST_USERS["negotiator_headers"]


@pytest.fixture
def authority_headers() -> dict:
    return TEST_USERS["authority_headers"]


@pytest.fixture
def chair_headers() -> dict:
    return TEST_USERS["chair_headers"]


@pytest.fixture
def chair_2_headers() -> dict:
    return TEST_USERS["chair_2_headers"]


@pytest.fixture
def utility_planner_headers() -> dict:
    """Shared UtilityPlanner headers.

    Only for calls that never pass a utility identity check: use
    ``make_utility_planner_headers(utility["id"])`` whenever the call is
    ownership-gated, which is every capacity revision, load study, capacity
    reservation and energization commitment.
    """
    return TEST_USERS["utility_planner_headers"]
