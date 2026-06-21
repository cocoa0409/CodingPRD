"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def dispatch_manager_headers():
    return TEST_USERS["dispatch_manager_headers"]


@pytest.fixture
def sort_associate_headers():
    return TEST_USERS["sort_associate_headers"]


@pytest.fixture
def customer_service_agent_headers():
    return TEST_USERS["customer_service_agent_headers"]


@pytest.fixture
def driver_headers():
    return TEST_USERS["driver_headers"]
