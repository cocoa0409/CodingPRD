"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (so test_helpers is importable) and the server
lifecycle (restarting the API server before every test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def sales_associate_headers():
    return TEST_USERS["sales_associate_headers"]


@pytest.fixture
def rental_clerk_headers():
    return TEST_USERS["rental_clerk_headers"]


@pytest.fixture
def accounts_manager_headers():
    return TEST_USERS["accounts_manager_headers"]


@pytest.fixture
def inventory_manager_headers():
    return TEST_USERS["inventory_manager_headers"]


@pytest.fixture
def contractor_headers():
    return TEST_USERS["contractor_headers"]
