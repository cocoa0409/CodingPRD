"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def district_admin_headers():
    return TEST_USERS["district_admin_headers"]


@pytest.fixture
def ditch_rider_headers():
    return TEST_USERS["ditch_rider_headers"]


@pytest.fixture
def water_user_headers():
    return TEST_USERS["water_user_headers"]
