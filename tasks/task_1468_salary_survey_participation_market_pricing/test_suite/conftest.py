"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def vendor_admin_headers():
    return TEST_USERS["vendor_admin_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def hr_director_headers():
    return TEST_USERS["hr_director_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]
