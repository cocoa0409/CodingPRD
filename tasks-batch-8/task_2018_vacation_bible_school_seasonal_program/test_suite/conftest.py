"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def parent_headers():
    return TEST_USERS["parent_headers"]


@pytest.fixture
def volunteer_headers():
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def check_in_staff_headers():
    return TEST_USERS["check_in_staff_headers"]


@pytest.fixture
def registration_coordinator_headers():
    return TEST_USERS["registration_coordinator_headers"]


@pytest.fixture
def volunteer_coordinator_headers():
    return TEST_USERS["volunteer_coordinator_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def program_director_headers():
    return TEST_USERS["program_director_headers"]
