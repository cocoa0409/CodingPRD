"""Pytest fixtures exposing test_helpers infrastructure for the Earned Wage Access suite."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["payroll_officer_headers"]


@pytest.fixture
def poster_headers():
    return TEST_USERS["payroll_poster_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def worker_headers():
    return TEST_USERS["worker_headers"]
