"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def systems_designer_headers():
    return TEST_USERS["systems_designer_headers"]


@pytest.fixture
def project_manager_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def low_voltage_tech_headers():
    return TEST_USERS["low_voltage_tech_headers"]


@pytest.fixture
def support_engineer_headers():
    return TEST_USERS["support_engineer_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]
