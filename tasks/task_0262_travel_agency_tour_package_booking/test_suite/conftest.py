"""Pytest fixtures exposing test_helpers infrastructure (Travel Agency Tour Booking API)."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def agency_admin_headers():
    return TEST_USERS["agency_admin_headers"]


@pytest.fixture
def travel_agent_headers():
    return TEST_USERS["travel_agent_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def supplier_headers():
    return TEST_USERS["supplier_headers"]
