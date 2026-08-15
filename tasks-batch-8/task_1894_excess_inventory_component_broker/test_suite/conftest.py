"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def broker_ops_headers():
    return TEST_USERS["broker_ops_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def finance_admin_headers():
    return TEST_USERS["finance_admin_headers"]


@pytest.fixture
def seller_headers():
    return TEST_USERS["seller_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
