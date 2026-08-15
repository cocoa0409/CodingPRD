"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def route_planner_headers():
    return TEST_USERS["route_planner_headers"]


@pytest.fixture
def driver_headers():
    return TEST_USERS["driver_headers"]


@pytest.fixture
def lab_tech_headers():
    return TEST_USERS["lab_tech_headers"]


@pytest.fixture
def settlement_clerk_headers():
    return TEST_USERS["settlement_clerk_headers"]


@pytest.fixture
def ehs_officer_headers():
    return TEST_USERS["ehs_officer_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]


@pytest.fixture
def tank_installer_headers():
    return TEST_USERS["tank_installer_headers"]
