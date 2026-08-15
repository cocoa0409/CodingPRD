"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def bu_approver_headers():
    return TEST_USERS["bu_approver_headers"]


@pytest.fixture
def mobility_approver_headers():
    return TEST_USERS["mobility_approver_headers"]


@pytest.fixture
def payroll_headers():
    return TEST_USERS["payroll_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def vendor_coordinator_headers():
    return TEST_USERS["vendor_coordinator_headers"]


@pytest.fixture
def tax_vendor_headers():
    return TEST_USERS["tax_vendor_headers"]


@pytest.fixture
def assignee_headers():
    return TEST_USERS["assignee_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
