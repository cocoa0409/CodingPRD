"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def order_manager_headers():
    return TEST_USERS["order_manager_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def warehouse_operator_headers():
    return TEST_USERS["warehouse_operator_headers"]


@pytest.fixture
def qa_lead_headers():
    return TEST_USERS["qa_lead_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def contract_admin_headers():
    return TEST_USERS["contract_admin_headers"]
