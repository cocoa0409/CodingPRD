"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns the server lifecycle and injects API_BASE_URL; these tests
assume the server is already running and freshly restarted (empty database,
logical clock at the PRD §2.6 startup value) before every test.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def sales_director_headers():
    return TEST_USERS["sales_director_headers"]


@pytest.fixture
def sales_agent_headers():
    return TEST_USERS["sales_agent_headers"]


@pytest.fixture
def construction_manager_headers():
    return TEST_USERS["construction_manager_headers"]


@pytest.fixture
def buyer_headers():
    return TEST_USERS["buyer_headers"]
