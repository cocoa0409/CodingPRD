"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import NO_AUTH_HEADERS, TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def agent_headers():
    return TEST_USERS["support_agent_headers"]


@pytest.fixture
def second_agent_headers():
    return TEST_USERS["second_support_agent_headers"]


@pytest.fixture
def owner_headers():
    """Placeholder Owner identity — only for calls that are not ownership-gated."""
    return TEST_USERS["owner_headers"]


@pytest.fixture
def member_headers():
    """Placeholder Member identity — only for calls that are not ownership-gated."""
    return TEST_USERS["member_headers"]


@pytest.fixture
def billing_admin_headers():
    """Placeholder BillingAdmin identity — only for calls that are not ownership-gated."""
    return TEST_USERS["billing_admin_headers"]


@pytest.fixture
def technician_headers():
    """Placeholder Technician identity — only for calls that are not ownership-gated."""
    return TEST_USERS["technician_headers"]


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
