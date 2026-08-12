"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def gate_headers():
    return TEST_USERS["gate_headers"]


@pytest.fixture
def lifeguard_headers():
    return TEST_USERS["lifeguard_headers"]


@pytest.fixture
def passholder_headers():
    return TEST_USERS["passholder_headers"]
