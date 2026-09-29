"""Pytest fixtures exposing the shuttle-service test helpers."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def contract_admin_headers():
    return TEST_USERS["contract_admin_headers"]


@pytest.fixture
def client_liaison_headers():
    return TEST_USERS["client_liaison_headers"]


@pytest.fixture
def ops_planner_headers():
    return TEST_USERS["ops_planner_headers"]


@pytest.fixture
def fleet_manager_headers():
    return TEST_USERS["fleet_manager_headers"]


@pytest.fixture
def driver_user_headers():
    return TEST_USERS["driver_user_headers"]
