"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def tax_accountant_headers():
    return TEST_USERS["tax_accountant_headers"]


@pytest.fixture
def tax_manager_headers():
    return TEST_USERS["tax_manager_headers"]


@pytest.fixture
def tax_director_headers():
    return TEST_USERS["tax_director_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
