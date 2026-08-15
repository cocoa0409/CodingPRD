"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def program_manager_headers():
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def operations_analyst_headers():
    return TEST_USERS["operations_analyst_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def cardholder_ops_headers():
    return TEST_USERS["cardholder_ops_headers"]
