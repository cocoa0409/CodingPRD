"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def sysadmin_headers():
    return TEST_USERS["sysadmin_headers"]


@pytest.fixture
def bed_manager_headers():
    return TEST_USERS["bed_manager_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def house_supervisor_headers():
    return TEST_USERS["house_supervisor_headers"]


@pytest.fixture
def capacity_planner_headers():
    return TEST_USERS["capacity_planner_headers"]


@pytest.fixture
def accepting_physician_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["accepting_physician_headers"]
