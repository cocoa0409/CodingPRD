"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def org_admin_headers():
    return TEST_USERS["org_admin_headers"]


@pytest.fixture
def audit_engineer_headers():
    return TEST_USERS["audit_engineer_headers"]


@pytest.fixture
def remediation_vendor_headers():
    return TEST_USERS["remediation_vendor_headers"]


@pytest.fixture
def compliance_manager_headers():
    return TEST_USERS["compliance_manager_headers"]
