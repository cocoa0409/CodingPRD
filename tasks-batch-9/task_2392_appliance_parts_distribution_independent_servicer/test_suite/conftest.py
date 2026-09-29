"""Pytest fixtures exposing the generated test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def servicer_headers():
    return TEST_USERS["servicer_headers"]


@pytest.fixture
def branch_counter_rep_headers():
    return TEST_USERS["branch_counter_rep_headers"]


@pytest.fixture
def credit_manager_headers():
    return TEST_USERS["credit_manager_headers"]


@pytest.fixture
def credit_manager_two_headers():
    return TEST_USERS["credit_manager_two_headers"]


@pytest.fixture
def warranty_admin_headers():
    return TEST_USERS["warranty_admin_headers"]


@pytest.fixture
def pricing_admin_headers():
    return TEST_USERS["pricing_admin_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
