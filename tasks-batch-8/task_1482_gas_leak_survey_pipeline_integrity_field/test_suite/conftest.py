"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def integrity_analyst_headers():
    return TEST_USERS["integrity_analyst_headers"]


@pytest.fixture
def field_technician_headers():
    return TEST_USERS["field_technician_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def dispatch_coordinator_headers():
    return TEST_USERS["dispatch_coordinator_headers"]


@pytest.fixture
def calibration_tech_headers():
    return TEST_USERS["calibration_tech_headers"]
