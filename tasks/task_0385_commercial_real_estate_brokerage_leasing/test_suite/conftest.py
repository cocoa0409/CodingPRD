"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_admin_headers, make_listing_broker_headers, make_tenant_broker_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def listing_broker_headers():
    return TEST_USERS["listing_broker_headers"]


@pytest.fixture
def tenant_broker_headers():
    return TEST_USERS["tenant_broker_headers"]
