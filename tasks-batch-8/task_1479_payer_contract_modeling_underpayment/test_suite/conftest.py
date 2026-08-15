"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def contract_analyst_headers():
    return TEST_USERS["contract_analyst_headers"]


@pytest.fixture
def contract_manager_headers():
    return TEST_USERS["contract_manager_headers"]


@pytest.fixture
def revenue_integrity_analyst_headers():
    return TEST_USERS["revenue_integrity_analyst_headers"]


@pytest.fixture
def recovery_manager_headers():
    return TEST_USERS["recovery_manager_headers"]


@pytest.fixture
def finance_director_headers():
    return TEST_USERS["finance_director_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
