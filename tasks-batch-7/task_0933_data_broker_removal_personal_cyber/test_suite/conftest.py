"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def privacy_agent_headers():
    return TEST_USERS["privacy_agent_headers"]


@pytest.fixture
def privacy_agent_beta_headers():
    return TEST_USERS["privacy_agent_beta_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def account_owner_headers():
    return TEST_USERS["account_owner_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
