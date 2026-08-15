"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def ops_controller_headers():
    return TEST_USERS["ops_controller_headers"]


@pytest.fixture
def airfield_inspector_headers():
    return TEST_USERS["airfield_inspector_headers"]


@pytest.fixture
def maintenance_lead_headers():
    return TEST_USERS["maintenance_lead_headers"]


@pytest.fixture
def airline_coordinator_headers():
    return TEST_USERS["airline_coordinator_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]
