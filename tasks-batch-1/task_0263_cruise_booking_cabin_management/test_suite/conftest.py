"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH so test_helpers is importable, and owns server
lifecycle — these fixtures only wire the shared client and role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def revenue_manager_headers():
    return TEST_USERS["revenue_manager_headers"]


@pytest.fixture
def reservations_agent_headers():
    return TEST_USERS["reservations_agent_headers"]


@pytest.fixture
def port_agent_headers():
    return TEST_USERS["port_agent_headers"]


@pytest.fixture
def guest_user_headers():
    return TEST_USERS["guest_user_headers"]
