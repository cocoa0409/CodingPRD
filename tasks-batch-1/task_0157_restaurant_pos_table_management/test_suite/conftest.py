"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def host_headers():
    return TEST_USERS["host_headers"]


@pytest.fixture
def kitchen_headers():
    return TEST_USERS["kitchen_headers"]


@pytest.fixture
def server_headers():
    return TEST_USERS["server_headers"]
