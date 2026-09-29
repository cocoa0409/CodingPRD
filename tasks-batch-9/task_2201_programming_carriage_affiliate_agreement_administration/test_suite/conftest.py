"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def network_admin_headers():
    return TEST_USERS["network_admin_headers"]


@pytest.fixture
def affiliate_sales_exec_headers():
    return TEST_USERS["affiliate_sales_exec_headers"]


@pytest.fixture
def affiliate_sales_exec_2_headers():
    return TEST_USERS["affiliate_sales_exec_2_headers"]


@pytest.fixture
def revenue_accountant_headers():
    return TEST_USERS["revenue_accountant_headers"]


@pytest.fixture
def revenue_accountant_2_headers():
    return TEST_USERS["revenue_accountant_2_headers"]


@pytest.fixture
def audit_manager_headers():
    return TEST_USERS["audit_manager_headers"]


@pytest.fixture
def audit_manager_2_headers():
    return TEST_USERS["audit_manager_2_headers"]


@pytest.fixture
def rights_administrator_headers():
    return TEST_USERS["rights_administrator_headers"]


@pytest.fixture
def distributor_liaison_headers():
    """A liaison identity bound to no persisted operator; ownership-scoped
    calls must instead use make_distributor_liaison_headers(distributor_id)."""
    return TEST_USERS["distributor_liaison_headers"]
