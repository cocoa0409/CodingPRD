"""Shared pytest fixtures for the private-fleet backhaul operations suite.

The server is restarted before every test, so each test sees an empty database
and must build all of its state through the API.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_helpers import TEST_USERS, api_client  # noqa: E402


@pytest.fixture(scope="session")
def api():
    """The typed API client bound to API_BASE_URL."""
    return api_client


@pytest.fixture
def planner():
    """Request headers for a FleetPlanner operator."""
    return TEST_USERS["fleet_planner_headers"]


@pytest.fixture
def manager():
    """Request headers for a TransportManager operator."""
    return TEST_USERS["transport_manager_headers"]


@pytest.fixture
def payroll():
    """Request headers for a PayrollAnalyst operator."""
    return TEST_USERS["payroll_analyst_headers"]


@pytest.fixture
def safety():
    """Request headers for a SafetyManager operator."""
    return TEST_USERS["safety_manager_headers"]


@pytest.fixture
def maintenance():
    """Request headers for a MaintenanceCoordinator operator."""
    return TEST_USERS["maintenance_coordinator_headers"]


@pytest.fixture
def driver_user():
    """Request headers for a generic Driver operator."""
    return TEST_USERS["driver_headers"]
