"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def fund_admin_headers():
    return TEST_USERS["fund_admin_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def transfer_agent_headers():
    return TEST_USERS["transfer_agent_headers"]


@pytest.fixture
def portfolio_manager_headers():
    return TEST_USERS["portfolio_manager_headers"]


@pytest.fixture
def investor_headers():
    return TEST_USERS["investor_headers"]
