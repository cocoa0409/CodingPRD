"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed externally; tests assume the API is reachable.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Shared API client. The server is already running."""
    return api_client


@pytest.fixture
def team_admin_headers():
    return TEST_USERS["team_admin"]


@pytest.fixture
def medical_staff_headers():
    return TEST_USERS["medical_staff"]


@pytest.fixture
def team_physician_headers():
    return TEST_USERS["team_physician"]


@pytest.fixture
def performance_staff_headers():
    return TEST_USERS["performance_staff"]


@pytest.fixture
def billing_staff_headers():
    return TEST_USERS["billing_staff"]


@pytest.fixture
def coaching_staff_headers():
    return TEST_USERS["coaching_staff"]
