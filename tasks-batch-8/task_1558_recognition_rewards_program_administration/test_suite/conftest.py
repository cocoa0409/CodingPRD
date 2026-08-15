"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def hr_admin_headers():
    return TEST_USERS["hr_admin_headers"]


@pytest.fixture
def finance_admin_headers():
    return TEST_USERS["finance_admin_headers"]


@pytest.fixture
def payroll_specialist_headers():
    return TEST_USERS["payroll_specialist_headers"]


@pytest.fixture
def vendor_ops_headers():
    return TEST_USERS["vendor_ops_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def employee_headers():
    return TEST_USERS["employee_headers"]
