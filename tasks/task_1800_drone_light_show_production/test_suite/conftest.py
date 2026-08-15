"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def planner_headers():
    return TEST_USERS["planner_headers"]


@pytest.fixture
def planner_2_headers():
    return TEST_USERS["planner_2_headers"]


@pytest.fixture
def authority_headers():
    return TEST_USERS["authority_headers"]


@pytest.fixture
def authority_2_headers():
    return TEST_USERS["authority_2_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def safety_officer_2_headers():
    return TEST_USERS["safety_officer_2_headers"]


@pytest.fixture
def fleet_manager_headers():
    return TEST_USERS["fleet_manager_headers"]


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]
