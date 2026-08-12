"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the runner; tests assume the API is reachable.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server is restarted per test by the runner."""
    return api_client


@pytest.fixture
def van_line_admin_headers():
    return TEST_USERS["van_line_admin_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def arbitrator_headers():
    return TEST_USERS["arbitrator_headers"]


@pytest.fixture
def booking_agent_headers():
    return TEST_USERS["booking_agent_headers"]


@pytest.fixture
def origin_agent_headers():
    return TEST_USERS["origin_agent_headers"]


@pytest.fixture
def hauling_agent_headers():
    return TEST_USERS["hauling_agent_headers"]


@pytest.fixture
def destination_agent_headers():
    return TEST_USERS["destination_agent_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
