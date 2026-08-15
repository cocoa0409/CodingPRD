"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import NO_AUTH_HEADERS, TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def route_driver_headers():
    return TEST_USERS["route_driver_headers"]


@pytest.fixture
def plant_operator_headers():
    return TEST_USERS["plant_operator_headers"]


@pytest.fixture
def billing_admin_headers():
    return TEST_USERS["billing_admin_headers"]


@pytest.fixture
def no_auth_headers():
    return dict(NO_AUTH_HEADERS)
