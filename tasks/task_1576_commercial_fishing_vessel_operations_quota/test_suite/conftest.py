"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def vessel_owner_headers():
    return TEST_USERS["vessel_owner_headers"]


@pytest.fixture
def captain_headers():
    return TEST_USERS["captain_headers"]


@pytest.fixture
def crew_member_headers():
    return TEST_USERS["crew_member_headers"]


@pytest.fixture
def observer_headers():
    return TEST_USERS["observer_headers"]
