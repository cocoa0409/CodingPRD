"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ANONYMOUS_HEADERS, ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_ops_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["policy_officer_headers"]


@pytest.fixture
def opener_headers():
    return TEST_USERS["policy_officer_opener_headers"]


@pytest.fixture
def decider_headers():
    return TEST_USERS["policy_officer_decider_headers"]


@pytest.fixture
def agent_headers():
    return TEST_USERS["review_agent_headers"]


@pytest.fixture
def storefront_headers():
    return TEST_USERS["storefront_headers"]


@pytest.fixture
def developer_headers():
    return TEST_USERS["developer_headers"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS
