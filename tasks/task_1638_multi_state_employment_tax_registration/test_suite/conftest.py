"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner manages server lifecycle and PYTHONPATH; tests
assume the server is already running at API_BASE_URL.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def tax_director_headers():
    return TEST_USERS["tax_director_headers"]


@pytest.fixture
def nexus_analyst_headers():
    return TEST_USERS["nexus_analyst_headers"]


@pytest.fixture
def ui_specialist_headers():
    return TEST_USERS["ui_specialist_headers"]


@pytest.fixture
def payroll_compliance_lead_headers():
    return TEST_USERS["payroll_compliance_lead_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def employee_headers():
    return TEST_USERS["employee_headers"]
