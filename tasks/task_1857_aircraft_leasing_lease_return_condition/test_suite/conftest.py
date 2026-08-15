"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def lessor_admin_headers():
    return TEST_USERS["lessor_admin_headers"]


@pytest.fixture
def credit_officer_headers():
    return TEST_USERS["credit_officer_headers"]


@pytest.fixture
def credit_officer_2_headers():
    return TEST_USERS["credit_officer_2_headers"]


@pytest.fixture
def legal_approver_headers():
    return TEST_USERS["legal_approver_headers"]


@pytest.fixture
def legal_approver_2_headers():
    return TEST_USERS["legal_approver_2_headers"]


@pytest.fixture
def finance_manager_headers():
    return TEST_USERS["finance_manager_headers"]
