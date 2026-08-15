"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def rack_price_analyst_headers():
    return TEST_USERS["rack_price_analyst_headers"]


@pytest.fixture
def allocation_manager_headers():
    return TEST_USERS["allocation_manager_headers"]


@pytest.fixture
def terminal_operator_headers():
    return TEST_USERS["terminal_operator_headers"]


@pytest.fixture
def exchange_coordinator_headers():
    return TEST_USERS["exchange_coordinator_headers"]


@pytest.fixture
def credit_analyst_headers():
    return TEST_USERS["credit_analyst_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def contract_admin_headers():
    return TEST_USERS["contract_admin_headers"]
