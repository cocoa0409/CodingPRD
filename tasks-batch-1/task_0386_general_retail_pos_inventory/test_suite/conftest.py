"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable and injects API_BASE_URL
before the pytest subprocess starts. These tests assume the server is already
running and reachable; they never start, stop, or health-check it.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def store_manager_headers():
    return TEST_USERS["store_manager_headers"]


@pytest.fixture
def cashier_headers():
    return TEST_USERS["cashier_headers"]


@pytest.fixture
def inventory_clerk_headers():
    return TEST_USERS["inventory_clerk_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
