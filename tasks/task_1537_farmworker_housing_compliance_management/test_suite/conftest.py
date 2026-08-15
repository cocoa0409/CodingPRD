"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def operator_admin_headers():
    return TEST_USERS["operator_admin_headers"]


@pytest.fixture
def site_manager_headers():
    return TEST_USERS["site_manager_headers"]


@pytest.fixture
def maintenance_lead_headers():
    return TEST_USERS["maintenance_lead_headers"]


@pytest.fixture
def compliance_inspector_headers():
    return TEST_USERS["compliance_inspector_headers"]


@pytest.fixture
def intake_coordinator_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def resident_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["resident_headers"]
