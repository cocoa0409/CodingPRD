"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def hr_admin_headers():
    return TEST_USERS["hr_admin_headers"]


@pytest.fixture
def hiring_manager_headers():
    return TEST_USERS["hiring_manager_headers"]


@pytest.fixture
def buddy_headers():
    return TEST_USERS["buddy_headers"]


@pytest.fixture
def new_hire_headers():
    return TEST_USERS["new_hire_headers"]


@pytest.fixture
def it_provisioner_headers():
    return TEST_USERS["it_provisioner_headers"]


@pytest.fixture
def adjudicator_headers():
    return TEST_USERS["adjudicator_headers"]


@pytest.fixture
def payroll_ops_headers():
    return TEST_USERS["payroll_ops_headers"]
