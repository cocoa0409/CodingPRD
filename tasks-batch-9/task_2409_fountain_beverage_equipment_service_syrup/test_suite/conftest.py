"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def admin_headers():
    """NetworkAdmin — admin-001."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_alt_headers():
    """A second NetworkAdmin — admin-002, for segregation-of-duty pairings."""
    return TEST_USERS["admin_alt_headers"]


@pytest.fixture
def planner_headers():
    """SupplyPlanner — planner-001."""
    return TEST_USERS["planner_headers"]


@pytest.fixture
def planner_alt_headers():
    return TEST_USERS["planner_alt_headers"]


@pytest.fixture
def driver_headers():
    """RouteDriver — driver-001."""
    return TEST_USERS["driver_headers"]


@pytest.fixture
def driver_alt_headers():
    return TEST_USERS["driver_alt_headers"]


@pytest.fixture
def technician_headers():
    """ServiceTechnician — tech-001."""
    return TEST_USERS["technician_headers"]


@pytest.fixture
def technician_alt_headers():
    """A second ServiceTechnician — tech-002, for assignment checks."""
    return TEST_USERS["technician_alt_headers"]


@pytest.fixture
def officer_headers():
    """ComplianceOfficer — officer-001."""
    return TEST_USERS["officer_headers"]


@pytest.fixture
def officer_alt_headers():
    """A second ComplianceOfficer — officer-002, for waiver segregation."""
    return TEST_USERS["officer_alt_headers"]


@pytest.fixture
def outlet_manager_headers():
    """An OutletManager whose X-User-ID is not any real outlet id."""
    return TEST_USERS["outlet_manager_headers"]
