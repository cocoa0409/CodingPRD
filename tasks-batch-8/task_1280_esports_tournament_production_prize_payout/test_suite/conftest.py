"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def organizer_admin_headers():
    return TEST_USERS["organizer_admin_headers"]


@pytest.fixture
def tournament_director_headers():
    return TEST_USERS["tournament_director_headers"]


@pytest.fixture
def team_manager_headers():
    return TEST_USERS["team_manager_headers"]


@pytest.fixture
def player_headers():
    return TEST_USERS["player_headers"]


@pytest.fixture
def referee_headers():
    return TEST_USERS["referee_headers"]


@pytest.fixture
def anti_cheat_investigator_headers():
    return TEST_USERS["anti_cheat_investigator_headers"]


@pytest.fixture
def broadcast_producer_headers():
    return TEST_USERS["broadcast_producer_headers"]


@pytest.fixture
def payout_officer_headers():
    return TEST_USERS["payout_officer_headers"]


@pytest.fixture
def sponsor_manager_headers():
    return TEST_USERS["sponsor_manager_headers"]
