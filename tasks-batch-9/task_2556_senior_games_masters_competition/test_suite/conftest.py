"""Pytest fixtures exposing the test_helpers infrastructure.

The server lifecycle is owned by prd-bench-local-runner: the server is
restarted before every individual test, so every test starts from an empty
database and builds its own preconditions.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client, reset_clock


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client aimed at API_BASE_URL."""
    return api_client


@pytest.fixture
def games_admin_headers():
    return TEST_USERS["games_admin_headers"]


@pytest.fixture
def registration_officer_headers():
    return TEST_USERS["registration_officer_headers"]


@pytest.fixture
def medical_director_headers():
    return TEST_USERS["medical_director_headers"]


@pytest.fixture
def records_ratifier_headers():
    return TEST_USERS["records_ratifier_headers"]


@pytest.fixture
def sponsor_liaison_headers():
    return TEST_USERS["sponsor_liaison_headers"]


@pytest.fixture
def athlete_headers():
    return TEST_USERS["athlete_headers"]


@pytest.fixture
def sport_official_headers():
    return TEST_USERS["sport_official_headers"]


@pytest.fixture
def clock_at_epoch():
    """Park the logical clock back at its documented starting instant."""
    return reset_clock()
