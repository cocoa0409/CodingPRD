"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle, PYTHONPATH and API_BASE_URL are owned by prd-bench-local-runner.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The runner restarts the server before each test."""
    return api_client


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["technician_headers"]


@pytest.fixture
def service_advisor_headers():
    return TEST_USERS["service_advisor_headers"]


@pytest.fixture
def store_manager_headers():
    return TEST_USERS["store_manager_headers"]
