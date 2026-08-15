"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def lease_admin_headers():
    return TEST_USERS["lease_admin_headers"]


@pytest.fixture
def fleet_planner_headers():
    return TEST_USERS["fleet_planner_headers"]


@pytest.fixture
def maintenance_controller_headers():
    return TEST_USERS["maintenance_controller_headers"]


@pytest.fixture
def billing_analyst_headers():
    return TEST_USERS["billing_analyst_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def lessee_rep_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["lessee_rep_headers"]
