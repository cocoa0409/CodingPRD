"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def scheduler_admin_headers():
    return TEST_USERS["scheduler_admin_headers"]


@pytest.fixture
def terminal_agent_headers():
    return TEST_USERS["terminal_agent_headers"]


@pytest.fixture
def crew_planner_headers():
    return TEST_USERS["crew_planner_headers"]


@pytest.fixture
def customer_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["customer_headers"]
