"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def payroll_admin_headers():
    return TEST_USERS["payroll_admin_headers"]


@pytest.fixture
def payroll_preparer_headers():
    return TEST_USERS["payroll_preparer_headers"]


@pytest.fixture
def payroll_preparer_alt_headers():
    return TEST_USERS["payroll_preparer_alt_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_alt_headers():
    return TEST_USERS["compliance_officer_alt_headers"]


@pytest.fixture
def employee_headers():
    return TEST_USERS["employee_headers"]


@pytest.fixture
def shift_manager_headers():
    return TEST_USERS["shift_manager_headers"]
