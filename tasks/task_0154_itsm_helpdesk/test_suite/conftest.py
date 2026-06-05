"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH so test_helpers is importable, sets API_BASE_URL,
and restarts the server before each test (empty DB + reset clock).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def requester_headers():
    return TEST_USERS["requester_headers"]


@pytest.fixture
def agent_headers():
    return TEST_USERS["agent_headers"]


@pytest.fixture
def change_manager_headers():
    return TEST_USERS["change_manager_headers"]


@pytest.fixture
def cab_member_headers():
    return TEST_USERS["cab_member_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
