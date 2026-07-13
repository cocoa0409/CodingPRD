"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def intake_coordinator_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def nutritionist_headers():
    return TEST_USERS["nutritionist_headers"]


@pytest.fixture
def route_manager_headers():
    return TEST_USERS["route_manager_headers"]


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def contribution_clerk_headers():
    return TEST_USERS["contribution_clerk_headers"]


@pytest.fixture
def volunteer_driver_headers():
    return TEST_USERS["volunteer_driver_headers"]
