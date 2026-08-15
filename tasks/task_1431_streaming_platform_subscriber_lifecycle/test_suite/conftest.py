"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def subscriber_headers():
    return TEST_USERS["subscriber_headers"]


@pytest.fixture
def support_agent_headers():
    return TEST_USERS["support_agent_headers"]


@pytest.fixture
def partner_billing_ops_headers():
    return TEST_USERS["partner_billing_ops_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
