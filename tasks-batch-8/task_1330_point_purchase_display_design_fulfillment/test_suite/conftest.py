"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def program_manager_headers():
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def designer_headers():
    return TEST_USERS["designer_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def warehouse_operator_headers():
    return TEST_USERS["warehouse_operator_headers"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def field_service_manager_headers():
    return TEST_USERS["field_service_manager_headers"]
