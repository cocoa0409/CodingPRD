"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_manager_headers():
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def giving_admin_headers():
    return TEST_USERS["giving_admin_headers"]


@pytest.fixture
def employee_headers():
    return TEST_USERS["employee_headers"]
