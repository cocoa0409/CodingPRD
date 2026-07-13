"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    anonymous_headers,
    api_client,
    no_auth_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def anonymous():
    return anonymous_headers()


@pytest.fixture
def unauthenticated():
    return no_auth_headers()


@pytest.fixture
def support_agent_headers():
    return TEST_USERS["support_agent_headers"]


@pytest.fixture
def abuse_analyst_headers():
    return TEST_USERS["abuse_analyst_headers"]


@pytest.fixture
def abuse_analyst_2_headers():
    return TEST_USERS["abuse_analyst_2_headers"]


@pytest.fixture
def billing_admin_headers():
    return TEST_USERS["billing_admin_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def registrant_headers():
    """Shared Registrant constant — safe only where no ownership check is reached."""
    return TEST_USERS["registrant_headers"]
