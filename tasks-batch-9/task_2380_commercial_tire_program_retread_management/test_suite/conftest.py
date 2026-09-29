"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def dealer_admin_headers():
    return TEST_USERS["dealer_admin_headers"]


@pytest.fixture
def fleet_manager_headers():
    return TEST_USERS["fleet_manager_headers"]


@pytest.fixture
def tire_technician_headers():
    return TEST_USERS["tire_technician_headers"]


@pytest.fixture
def casing_inspector_headers():
    return TEST_USERS["casing_inspector_headers"]


@pytest.fixture
def plant_scheduler_headers():
    return TEST_USERS["plant_scheduler_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def dispatch_coordinator_headers():
    return TEST_USERS["dispatch_coordinator_headers"]
