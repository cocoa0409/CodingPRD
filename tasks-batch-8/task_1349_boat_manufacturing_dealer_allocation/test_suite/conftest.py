"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def allocation_manager_headers():
    return TEST_USERS["allocation_manager_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def warranty_administrator_headers():
    return TEST_USERS["warranty_administrator_headers"]


@pytest.fixture
def dealer_principal_headers():
    return TEST_USERS["dealer_principal_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
