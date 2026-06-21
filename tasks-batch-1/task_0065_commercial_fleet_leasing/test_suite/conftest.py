"""Pytest fixtures exposing test_helpers infrastructure (commercial fleet leasing)."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def fleet_manager_headers():
    return TEST_USERS["fleet_manager_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def telematics_gateway_headers():
    return TEST_USERS["telematics_gateway_headers"]


@pytest.fixture
def lessee_headers():
    return TEST_USERS["lessee_headers"]
