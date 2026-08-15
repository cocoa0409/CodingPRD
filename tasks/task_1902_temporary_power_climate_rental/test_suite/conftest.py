"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def sales_engineer_headers():
    return TEST_USERS["sales_engineer_headers"]


@pytest.fixture
def depot_manager_headers():
    return TEST_USERS["depot_manager_headers"]


@pytest.fixture
def fleet_dispatcher_headers():
    return TEST_USERS["fleet_dispatcher_headers"]


@pytest.fixture
def field_technician_headers():
    return TEST_USERS["field_technician_headers"]


@pytest.fixture
def claims_assessor_headers():
    return TEST_USERS["claims_assessor_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
