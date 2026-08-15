"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def account_executive_headers():
    return TEST_USERS["account_executive_headers"]


@pytest.fixture
def flight_ops_headers():
    return TEST_USERS["flight_ops_headers"]


@pytest.fixture
def maintenance_planner_headers():
    return TEST_USERS["maintenance_planner_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def contracts_manager_headers():
    return TEST_USERS["contracts_manager_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
