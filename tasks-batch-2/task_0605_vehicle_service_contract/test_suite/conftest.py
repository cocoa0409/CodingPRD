"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_underwriter_headers():
    return TEST_USERS["admin_underwriter_headers"]


@pytest.fixture
def contract_admin_headers():
    return TEST_USERS["contract_admin_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def repair_facility_headers():
    return TEST_USERS["repair_facility_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
