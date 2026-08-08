"""Pytest fixtures exposing test_helpers infrastructure for the Mobile Fuel Delivery suite."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def fleet_manager_headers():
    return TEST_USERS["fleet_manager_headers"]


@pytest.fixture
def driver_headers():
    return TEST_USERS["driver_headers"]
