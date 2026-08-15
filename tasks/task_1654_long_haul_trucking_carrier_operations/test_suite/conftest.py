"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def fleet_admin_headers():
    return TEST_USERS["fleet_admin_headers"]


@pytest.fixture
def load_planner_headers():
    return TEST_USERS["load_planner_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def payroll_clerk_headers():
    return TEST_USERS["payroll_clerk_headers"]


@pytest.fixture
def driver_headers():
    return TEST_USERS["driver_headers"]
