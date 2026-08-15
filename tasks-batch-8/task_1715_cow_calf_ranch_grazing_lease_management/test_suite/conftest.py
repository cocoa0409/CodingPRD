"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ranch_manager_headers():
    return TEST_USERS["ranch_manager_headers"]


@pytest.fixture
def range_manager_headers():
    return TEST_USERS["range_manager_headers"]


@pytest.fixture
def herd_manager_headers():
    return TEST_USERS["herd_manager_headers"]


@pytest.fixture
def sales_agent_headers():
    return TEST_USERS["sales_agent_headers"]
