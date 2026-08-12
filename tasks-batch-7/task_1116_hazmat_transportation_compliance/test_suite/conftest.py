"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the test runner."""
    return api_client


@pytest.fixture
def carrier_admin_headers():
    return TEST_USERS["carrier_admin_headers"]


@pytest.fixture
def officer_a_headers():
    return TEST_USERS["officer_a_headers"]


@pytest.fixture
def officer_b_headers():
    return TEST_USERS["officer_b_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]
