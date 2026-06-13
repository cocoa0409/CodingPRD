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
def receiving_clerk_headers():
    return TEST_USERS["receiving_clerk_headers"]


@pytest.fixture
def price_manager_headers():
    return TEST_USERS["price_manager_headers"]


@pytest.fixture
def cashier_headers():
    return TEST_USERS["cashier_headers"]


@pytest.fixture
def inventory_auditor_headers():
    return TEST_USERS["inventory_auditor_headers"]


@pytest.fixture
def loyalty_member_headers():
    return TEST_USERS["loyalty_member_headers"]
