"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def facility_manager_headers():
    return TEST_USERS["facility_manager_headers"]


@pytest.fixture
def parking_attendant_headers():
    return TEST_USERS["parking_attendant_headers"]


@pytest.fixture
def revenue_auditor_headers():
    return TEST_USERS["revenue_auditor_headers"]


@pytest.fixture
def maintenance_supervisor_headers():
    return TEST_USERS["maintenance_supervisor_headers"]


@pytest.fixture
def security_officer_headers():
    return TEST_USERS["security_officer_headers"]


@pytest.fixture
def gate_device_headers():
    # Shared fallback: only safe for tests that do not exercise device identity.
    return TEST_USERS["gate_device_headers"]


@pytest.fixture
def monthly_parker_headers():
    # Shared fallback: only safe for tests that do not exercise parker ownership.
    return TEST_USERS["monthly_parker_headers"]
