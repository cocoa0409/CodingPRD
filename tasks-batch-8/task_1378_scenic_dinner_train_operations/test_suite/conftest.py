"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; these fixtures only
wire up the shared API client and the pre-built role headers.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server is already running at API_BASE_URL."""
    return api_client


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def mechanic_headers():
    return TEST_USERS["mechanic_headers"]


@pytest.fixture
def station_agent_headers():
    return TEST_USERS["station_agent_headers"]


@pytest.fixture
def crew_manager_headers():
    return TEST_USERS["crew_manager_headers"]


@pytest.fixture
def catering_manager_headers():
    return TEST_USERS["catering_manager_headers"]


@pytest.fixture
def operations_manager_headers():
    return TEST_USERS["operations_manager_headers"]
