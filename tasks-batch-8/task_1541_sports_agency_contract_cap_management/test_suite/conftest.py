"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def league_officer_headers():
    return TEST_USERS["league_officer_headers"]


@pytest.fixture
def agency_manager_headers():
    return TEST_USERS["agency_manager_headers"]


@pytest.fixture
def agent_headers():
    return TEST_USERS["agent_headers"]


@pytest.fixture
def team_headers():
    return TEST_USERS["team_headers"]


@pytest.fixture
def player_headers():
    return TEST_USERS["player_headers"]
