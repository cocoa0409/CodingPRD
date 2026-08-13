"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the runner; tests assume the API is reachable
at API_BASE_URL and starts empty for every test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def proxy_admin_headers():
    return TEST_USERS["proxy_admin_headers"]


@pytest.fixture
def transfer_agent_headers():
    return TEST_USERS["transfer_agent_headers"]


@pytest.fixture
def broker_headers():
    return TEST_USERS["broker_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def inspector_2_headers():
    return TEST_USERS["inspector_2_headers"]


@pytest.fixture
def shareholder_headers():
    return TEST_USERS["shareholder_headers"]
