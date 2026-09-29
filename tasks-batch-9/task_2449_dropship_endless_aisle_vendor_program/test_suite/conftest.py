"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def vendor_ops_analyst_headers():
    return TEST_USERS["vendor_ops_analyst_headers"]


@pytest.fixture
def merchandise_manager_headers():
    return TEST_USERS["merchandise_manager_headers"]


@pytest.fixture
def care_agent_headers():
    return TEST_USERS["care_agent_headers"]


@pytest.fixture
def vendor_user_headers():
    """Shared VendorUser constant. Use make_vendor_user_headers(vendor_id) whenever
    the call reaches a vendor-owned resource."""
    return TEST_USERS["vendor_user_headers"]
