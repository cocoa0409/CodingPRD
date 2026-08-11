"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def ops_agent_headers():
    return TEST_USERS["ops_agent_headers"]


@pytest.fixture
def counsel_headers():
    return TEST_USERS["counsel_headers"]


@pytest.fixture
def customer_admin_headers():
    """Fallback CustomerAdmin headers (shared, non-owning identity). Tests that
    exercise ownership-gated calls must use make_customer_admin_headers(company_id)."""
    return TEST_USERS["customer_admin_headers"]
