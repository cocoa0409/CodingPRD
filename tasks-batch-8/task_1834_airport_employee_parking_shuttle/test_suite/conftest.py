"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def parking_admin_headers():
    return TEST_USERS["parking_admin_headers"]


@pytest.fixture
def payroll_admin_headers():
    return TEST_USERS["payroll_admin_headers"]


@pytest.fixture
def enforcement_officer_headers():
    return TEST_USERS["enforcement_officer_headers"]


@pytest.fixture
def appeals_officer_headers():
    return TEST_USERS["appeals_officer_headers"]


@pytest.fixture
def shuttle_dispatcher_headers():
    return TEST_USERS["shuttle_dispatcher_headers"]


@pytest.fixture
def employee_headers():
    """Shared Employee headers — for non-ownership tests only."""
    return TEST_USERS["employee_headers"]
