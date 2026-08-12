"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; the server is restarted
before every test, so each test starts against an empty database and builds its
own preconditions via the test_helpers setup functions.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def cast_director_headers():
    return TEST_USERS["cast_director_headers"]


@pytest.fixture
def vendor_coordinator_headers():
    return TEST_USERS["vendor_coordinator_headers"]


@pytest.fixture
def gate_agent_headers():
    return TEST_USERS["gate_agent_headers"]


@pytest.fixture
def volunteer_coordinator_headers():
    return TEST_USERS["volunteer_coordinator_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
