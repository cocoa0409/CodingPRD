"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the test runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def production_manager_headers():
    return TEST_USERS["production_manager_headers"]


@pytest.fixture
def rigging_supervisor_headers():
    return TEST_USERS["rigging_supervisor_headers"]


@pytest.fixture
def structural_engineer_headers():
    return TEST_USERS["structural_engineer_headers"]


@pytest.fixture
def warehouse_chief_headers():
    return TEST_USERS["warehouse_chief_headers"]


@pytest.fixture
def safety_inspector_headers():
    return TEST_USERS["safety_inspector_headers"]


@pytest.fixture
def crew_chief_headers():
    return TEST_USERS["crew_chief_headers"]


@pytest.fixture
def client_contact_headers():
    return TEST_USERS["client_contact_headers"]
