"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    NO_AUTH_HEADERS,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.  Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def safety_officer_alt_headers():
    return TEST_USERS["safety_officer_alt_headers"]


@pytest.fixture
def grants_admin_headers():
    return TEST_USERS["grants_admin_headers"]


@pytest.fixture
def volunteer_headers():
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def crew_leader_headers():
    return TEST_USERS["crew_leader_headers"]


@pytest.fixture
def land_manager_headers():
    return TEST_USERS["land_manager_headers"]


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
