"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def dealer_admin_headers():
    return TEST_USERS["dealer_admin_headers"]


@pytest.fixture
def energy_engineer_headers():
    return TEST_USERS["energy_engineer_headers"]


@pytest.fixture
def service_tech_headers():
    return TEST_USERS["service_tech_headers"]


@pytest.fixture
def contract_manager_headers():
    return TEST_USERS["contract_manager_headers"]


@pytest.fixture
def facility_manager_headers():
    return TEST_USERS["facility_manager_headers"]
