"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    SAFETY_OFFICER_1_HEADERS,
    SAFETY_OFFICER_2_HEADERS,
    SAFETY_OFFICER_3_HEADERS,
    FIELD_TECHNICIAN_1_HEADERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def network_planner_headers():
    return TEST_USERS["network_planner_headers"]


@pytest.fixture
def test_supervisor_headers():
    return TEST_USERS["test_supervisor_headers"]


@pytest.fixture
def field_technician_headers():
    return TEST_USERS["field_technician_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def fault_crew_lead_headers():
    return TEST_USERS["fault_crew_lead_headers"]


@pytest.fixture
def dispatch_coordinator_headers():
    return TEST_USERS["dispatch_coordinator_headers"]


@pytest.fixture
def asset_engineer_headers():
    return TEST_USERS["asset_engineer_headers"]


@pytest.fixture
def safety_officer_1_headers():
    return SAFETY_OFFICER_1_HEADERS


@pytest.fixture
def safety_officer_2_headers():
    return SAFETY_OFFICER_2_HEADERS


@pytest.fixture
def safety_officer_3_headers():
    return SAFETY_OFFICER_3_HEADERS


@pytest.fixture
def field_technician_1_headers():
    return FIELD_TECHNICIAN_1_HEADERS
