"""Pytest fixtures exposing the shared test infrastructure.

The server is launched, killed and relaunched by the harness around every test,
so each test opens against an empty store with the logical clock reading its
documented default of 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the harness."""
    return api_client


@pytest.fixture
def corps_director_headers():
    return TEST_USERS["corps_director_headers"]


@pytest.fixture
def membership_coordinator_headers():
    return TEST_USERS["membership_coordinator_headers"]


@pytest.fixture
def tour_manager_headers():
    return TEST_USERS["tour_manager_headers"]


@pytest.fixture
def business_manager_headers():
    return TEST_USERS["business_manager_headers"]


@pytest.fixture
def second_business_manager_headers():
    return TEST_USERS["second_business_manager_headers"]


@pytest.fixture
def volunteer_screener_headers():
    return TEST_USERS["volunteer_screener_headers"]


@pytest.fixture
def second_volunteer_screener_headers():
    return TEST_USERS["second_volunteer_screener_headers"]


@pytest.fixture
def screener_as_tour_manager_headers():
    return TEST_USERS["screener_as_tour_manager_headers"]


@pytest.fixture
def no_auth_headers():
    return TEST_USERS["no_auth_headers"]
