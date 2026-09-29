"""Pytest fixtures exposing the shared test infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def conduct_officer_headers():
    return TEST_USERS["conduct_officer_headers"]


@pytest.fixture
def second_conduct_officer_headers():
    return TEST_USERS["second_conduct_officer_headers"]


@pytest.fixture
def bursar_headers():
    return TEST_USERS["bursar_headers"]


@pytest.fixture
def ra_headers():
    return TEST_USERS["ra_headers"]


@pytest.fixture
def student_headers():
    return TEST_USERS["student_headers"]
