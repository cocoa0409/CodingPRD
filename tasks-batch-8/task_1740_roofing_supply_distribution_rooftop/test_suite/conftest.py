"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def branch_manager_headers():
    return TEST_USERS["branch_manager_headers"]


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def credit_analyst_headers():
    return TEST_USERS["credit_analyst_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def warehouse_clerk_headers():
    return TEST_USERS["warehouse_clerk_headers"]


@pytest.fixture
def contractor_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["contractor_headers"]
