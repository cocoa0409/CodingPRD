"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def sales_agent_headers():
    return TEST_USERS["sales_agent_headers"]


@pytest.fixture
def dispatch_manager_headers():
    return TEST_USERS["dispatch_manager_headers"]


@pytest.fixture
def maintenance_controller_headers():
    return TEST_USERS["maintenance_controller_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def aircraft_owner_headers():
    return TEST_USERS["aircraft_owner_headers"]


@pytest.fixture
def crew_member_headers():
    return TEST_USERS["crew_member_headers"]
