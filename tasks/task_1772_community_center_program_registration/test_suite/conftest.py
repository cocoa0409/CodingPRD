"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def program_coordinator_headers():
    return TEST_USERS["program_coordinator_headers"]


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def scholarship_reviewer_headers():
    return TEST_USERS["scholarship_reviewer_headers"]


@pytest.fixture
def household_manager_headers():
    return TEST_USERS["household_manager_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["instructor_headers"]
