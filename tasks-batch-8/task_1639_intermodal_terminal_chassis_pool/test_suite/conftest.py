"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def terminal_manager_headers():
    return TEST_USERS["terminal_manager_headers"]


@pytest.fixture
def pool_administrator_headers():
    return TEST_USERS["pool_administrator_headers"]


@pytest.fixture
def yard_planner_headers():
    return TEST_USERS["yard_planner_headers"]


@pytest.fixture
def rail_coordinator_headers():
    return TEST_USERS["rail_coordinator_headers"]


@pytest.fixture
def gate_supervisor_headers():
    return TEST_USERS["gate_supervisor_headers"]


@pytest.fixture
def gate_clerk_headers():
    return TEST_USERS["gate_clerk_headers"]


@pytest.fixture
def maintenance_planner_headers():
    return TEST_USERS["maintenance_planner_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]
