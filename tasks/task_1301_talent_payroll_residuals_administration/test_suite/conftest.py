"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["payroll_admin_headers"]


@pytest.fixture
def accountant_headers():
    return TEST_USERS["production_accountant_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["payroll_clerk_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["payroll_supervisor_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["union_auditor_headers"]
