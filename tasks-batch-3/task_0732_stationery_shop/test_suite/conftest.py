"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def shop_admin_headers():
    return TEST_USERS["shop_admin_headers"]


@pytest.fixture
def customer_headers():
    """Fallback Customer headers — safe only for non-ownership tests
    (missing-payload, non-existent-resource, RBAC role-denial)."""
    return TEST_USERS["customer_headers"]


@pytest.fixture
def designer_headers():
    """Fallback Designer headers — safe only for non-ownership tests."""
    return TEST_USERS["designer_headers"]
