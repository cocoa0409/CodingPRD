"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def kitchen_manager_headers():
    return TEST_USERS["kitchen_manager_headers"]


@pytest.fixture
def food_safety_officer_headers():
    return TEST_USERS["food_safety_officer_headers"]


@pytest.fixture
def volunteer_headers():
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def guest_headers():
    return TEST_USERS["guest_headers"]


@pytest.fixture
def no_auth_headers():
    return dict(NO_AUTH_HEADERS)
