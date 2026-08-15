"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the runner; the API client is session-scoped.
Each test starts against an empty database (the server is restarted per test),
so every fixture builds its preconditions from scratch.
"""
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_coordinator_headers,
    make_ops_admin_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def client_agent_headers():
    return TEST_USERS["client_agent_headers"]


@pytest.fixture
def photographer_headers():
    return TEST_USERS["photographer_headers"]
