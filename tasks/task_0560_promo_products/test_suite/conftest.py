"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def catalog_admin_headers():
    return TEST_USERS["catalog_admin_headers"]


@pytest.fixture
def account_manager_headers():
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def production_manager_headers():
    return TEST_USERS["production_manager_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
