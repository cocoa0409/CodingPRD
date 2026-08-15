"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def lease_admin_headers():
    return TEST_USERS["lease_admin_headers"]


@pytest.fixture
def settlement_clerk_headers():
    return TEST_USERS["settlement_clerk_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def maintenance_coordinator_headers():
    return TEST_USERS["maintenance_coordinator_headers"]


@pytest.fixture
def driver_headers():
    return TEST_USERS["driver_headers"]
