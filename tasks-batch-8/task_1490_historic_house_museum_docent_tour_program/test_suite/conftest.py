"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def museum_admin_headers():
    return TEST_USERS["museum_admin_headers"]


@pytest.fixture
def curator_headers():
    return TEST_USERS["curator_headers"]


@pytest.fixture
def docent_coordinator_headers():
    return TEST_USERS["docent_coordinator_headers"]


@pytest.fixture
def front_desk_staff_headers():
    return TEST_USERS["front_desk_staff_headers"]


@pytest.fixture
def docent_headers():
    return TEST_USERS["docent_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
