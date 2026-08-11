"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's responsibility."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["shop_manager_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["move_coordinator_headers"]


@pytest.fixture
def agent_headers():
    return TEST_USERS["showroom_agent_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["technician_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]
