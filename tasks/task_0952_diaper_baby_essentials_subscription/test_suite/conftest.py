"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def support_agent_headers():
    return TEST_USERS["support_agent_headers"]


@pytest.fixture
def support_agent_2_headers():
    return TEST_USERS["support_agent_2_headers"]


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def ops_admin_2_headers():
    return TEST_USERS["ops_admin_2_headers"]


@pytest.fixture
def account_holder_headers():
    """Shared fallback — only for tests that never exercise ownership."""
    return TEST_USERS["account_holder_headers"]


@pytest.fixture
def registry_owner_headers():
    """Shared fallback — only for tests that never exercise ownership."""
    return TEST_USERS["registry_owner_headers"]


@pytest.fixture
def gift_purchaser_headers():
    """Shared fallback — only for tests that never exercise ownership."""
    return TEST_USERS["gift_purchaser_headers"]
