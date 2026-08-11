"""Pytest fixtures exposing the home-staging test helpers."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["staging_coordinator_headers"]


@pytest.fixture
def warehouse_headers():
    return TEST_USERS["warehouse_manager_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def listing_agent_headers():
    return TEST_USERS["listing_agent_headers"]


@pytest.fixture
def seller_headers():
    return TEST_USERS["seller_headers"]


@pytest.fixture
def brokerage_admin_headers():
    return TEST_USERS["brokerage_admin_headers"]


@pytest.fixture
def vendor_rep_headers():
    return TEST_USERS["vendor_rep_headers"]
