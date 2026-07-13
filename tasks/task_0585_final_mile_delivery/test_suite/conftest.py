"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, NO_AUTH_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def dispatch_planner_headers():
    return TEST_USERS["dispatch_planner_headers"]


@pytest.fixture
def dock_coordinator_headers():
    return TEST_USERS["dock_coordinator_headers"]


@pytest.fixture
def delivery_lead_headers():
    return TEST_USERS["delivery_lead_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
