"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (test_helpers importable) and server lifecycle.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def benefits_admin_headers():
    return TEST_USERS["benefits_admin_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def payroll_headers():
    return TEST_USERS["payroll_headers"]


@pytest.fixture
def system_headers():
    return TEST_USERS["system_headers"]


@pytest.fixture
def employee_headers():
    return TEST_USERS["employee_headers"]
