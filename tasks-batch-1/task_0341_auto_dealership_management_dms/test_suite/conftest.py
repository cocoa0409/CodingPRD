"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def inventory_clerk_headers():
    return TEST_USERS["inventory_clerk_headers"]


@pytest.fixture
def sales_manager_headers():
    return TEST_USERS["sales_manager_headers"]


@pytest.fixture
def finance_manager_headers():
    return TEST_USERS["finance_manager_headers"]


@pytest.fixture
def service_advisor_headers():
    return TEST_USERS["service_advisor_headers"]


@pytest.fixture
def title_clerk_headers():
    return TEST_USERS["title_clerk_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
