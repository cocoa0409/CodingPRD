"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["catalog_admin_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["production_operator_headers"]


@pytest.fixture
def customer_headers():
    """Fallback Customer headers (non-ownership tests only)."""
    return TEST_USERS["customer_headers"]
