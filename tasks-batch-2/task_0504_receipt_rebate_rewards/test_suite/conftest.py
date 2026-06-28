"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def review_agent_headers():
    return TEST_USERS["review_agent_headers"]


@pytest.fixture
def finance_admin_headers():
    return TEST_USERS["finance_admin_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
