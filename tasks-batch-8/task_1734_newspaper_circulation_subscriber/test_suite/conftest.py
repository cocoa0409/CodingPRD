"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def subscriber_headers():
    return TEST_USERS["subscriber_headers"]


@pytest.fixture
def service_rep_headers():
    return TEST_USERS["service_rep_headers"]


@pytest.fixture
def district_manager_headers():
    return TEST_USERS["district_manager_headers"]


@pytest.fixture
def circulation_director_headers():
    return TEST_USERS["circulation_director_headers"]
