"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def pm_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def sup_headers():
    return TEST_USERS["site_supervisor_headers"]


@pytest.fixture
def so_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def pay_headers():
    return TEST_USERS["payroll_clerk_headers"]


@pytest.fixture
def cust_headers():
    return TEST_USERS["customer_rep_headers"]
