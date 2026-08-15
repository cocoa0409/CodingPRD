"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def inventory_manager_headers():
    return TEST_USERS["inventory_manager_headers"]


@pytest.fixture
def sales_planner_headers():
    return TEST_USERS["sales_planner_headers"]


@pytest.fixture
def sales_manager_headers():
    return TEST_USERS["sales_manager_headers"]


@pytest.fixture
def production_coordinator_headers():
    return TEST_USERS["production_coordinator_headers"]


@pytest.fixture
def field_installer_headers():
    return TEST_USERS["field_installer_headers"]


@pytest.fixture
def operations_auditor_headers():
    return TEST_USERS["operations_auditor_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def finance_analyst_headers():
    return TEST_USERS["finance_analyst_headers"]
