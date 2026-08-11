"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; the API client simply
reads API_BASE_URL from the environment.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["event_coordinator_headers"]


@pytest.fixture
def treasurer_headers():
    return TEST_USERS["treasurer_headers"]


@pytest.fixture
def juror_headers():
    return TEST_USERS["juror_headers"]


@pytest.fixture
def gate_agent_headers():
    return TEST_USERS["gate_agent_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def vendor_headers():
    return TEST_USERS["vendor_headers"]
