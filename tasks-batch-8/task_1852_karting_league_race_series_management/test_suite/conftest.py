"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def league_admin_headers():
    return TEST_USERS["league_admin_headers"]


@pytest.fixture
def race_director_headers():
    return TEST_USERS["race_director_headers"]


@pytest.fixture
def race_director_2_headers():
    return TEST_USERS["race_director_2_headers"]


@pytest.fixture
def steward_headers():
    return TEST_USERS["steward_headers"]


@pytest.fixture
def steward_2_headers():
    return TEST_USERS["steward_2_headers"]


@pytest.fixture
def steward_9_headers():
    return TEST_USERS["steward_9_headers"]


@pytest.fixture
def driver_headers():
    return TEST_USERS["driver_headers"]
