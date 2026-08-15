"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner: the API server is
restarted before every test, so each test starts against an empty database
and the logical clock's startup default.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server is guaranteed reachable."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def risk_analyst_headers():
    return TEST_USERS["risk_analyst_headers"]


@pytest.fixture
def security_approver_headers():
    return TEST_USERS["security_approver_headers"]


@pytest.fixture
def vendor_contact_headers():
    return TEST_USERS["vendor_contact_headers"]
