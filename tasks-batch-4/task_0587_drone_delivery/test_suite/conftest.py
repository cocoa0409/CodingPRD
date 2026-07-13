"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def dispatch_operator_headers():
    return TEST_USERS["dispatch_operator_headers"]


@pytest.fixture
def flight_director_headers():
    return TEST_USERS["flight_director_headers"]


@pytest.fixture
def maintenance_tech_headers():
    return TEST_USERS["maintenance_tech_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
