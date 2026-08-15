"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def field_ops_headers():
    return TEST_USERS["field_ops_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def driver_headers():
    return TEST_USERS["driver_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]


@pytest.fixture
def plant_headers():
    return TEST_USERS["plant_headers"]


@pytest.fixture
def customer_contact_headers():
    return TEST_USERS["customer_contact_headers"]
