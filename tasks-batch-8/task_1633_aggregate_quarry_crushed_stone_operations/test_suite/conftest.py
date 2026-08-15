"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def quarry_admin_headers():
    return TEST_USERS["quarry_admin_headers"]


@pytest.fixture
def site_manager_headers():
    return TEST_USERS["site_manager_headers"]


@pytest.fixture
def blast_foreman_headers():
    return TEST_USERS["blast_foreman_headers"]


@pytest.fixture
def plant_operator_headers():
    return TEST_USERS["plant_operator_headers"]


@pytest.fixture
def scale_house_operator_headers():
    return TEST_USERS["scale_house_operator_headers"]


@pytest.fixture
def qc_technician_headers():
    return TEST_USERS["qc_technician_headers"]


@pytest.fixture
def sales_agent_headers():
    return TEST_USERS["sales_agent_headers"]


@pytest.fixture
def finance_clerk_headers():
    return TEST_USERS["finance_clerk_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]
