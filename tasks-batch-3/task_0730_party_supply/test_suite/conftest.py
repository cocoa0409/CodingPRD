"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def store_manager_headers():
    return TEST_USERS["store_manager_headers"]


@pytest.fixture
def store_clerk_headers():
    return TEST_USERS["store_clerk_headers"]


@pytest.fixture
def delivery_driver_headers():
    return TEST_USERS["delivery_driver_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
