"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def brewer_headers():
    """Brewer role with an identifier bound to no Brewer entity.

    Usable only where ownership is not the thing under test; ownership-gated
    calls must thread the acting Brewer entity's own id (PRD §2.1).
    """
    return TEST_USERS["brewer_headers"]


@pytest.fixture
def allocation_manager_headers():
    return TEST_USERS["allocation_manager_headers"]


@pytest.fixture
def allocation_manager_2_headers():
    return TEST_USERS["allocation_manager_2_headers"]


@pytest.fixture
def credit_manager_headers():
    return TEST_USERS["credit_manager_headers"]


@pytest.fixture
def warehouse_operator_headers():
    return TEST_USERS["warehouse_operator_headers"]


@pytest.fixture
def warehouse_operator_2_headers():
    return TEST_USERS["warehouse_operator_2_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def invalid_role_headers():
    return TEST_USERS["invalid_role_headers"]
