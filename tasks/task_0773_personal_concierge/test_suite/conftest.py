"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def concierge_agent_headers():
    return TEST_USERS["concierge_agent_headers"]


@pytest.fixture
def account_manager_headers():
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def finance_ops_headers():
    return TEST_USERS["finance_ops_headers"]
