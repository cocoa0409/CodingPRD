"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def crew_manager_headers():
    return TEST_USERS["crew_manager_headers"]


@pytest.fixture
def crew_caller_headers():
    return TEST_USERS["crew_caller_headers"]


@pytest.fixture
def employee_headers():
    """Shared Employee-role headers — only for probes that do not exercise
    ownership (ownership-gated flows must use make_employee_headers(emp_id))."""
    return TEST_USERS["employee_headers"]
