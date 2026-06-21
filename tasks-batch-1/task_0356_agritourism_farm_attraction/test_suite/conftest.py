"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and manages the server
lifecycle (restarting it before each test against an empty database).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def farm_manager_headers():
    return TEST_USERS["farm_manager_headers"]


@pytest.fixture
def gate_agent_headers():
    return TEST_USERS["gate_agent_headers"]


@pytest.fixture
def visitor_headers():
    return TEST_USERS["visitor_headers"]


@pytest.fixture
def group_leader_headers():
    return TEST_USERS["group_leader_headers"]
