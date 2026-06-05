"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable and injects API_BASE_URL.
The server is restarted before every test, so every test starts against an empty DB.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def payroll_admin_headers():
    return TEST_USERS["payroll_admin_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def supervisor2_headers():
    return TEST_USERS["supervisor2_headers"]


@pytest.fixture
def supervisor_editor_headers():
    return TEST_USERS["supervisor_editor_headers"]


@pytest.fixture
def employee_headers():
    return TEST_USERS["employee_headers"]
