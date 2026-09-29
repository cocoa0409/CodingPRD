"""Shared pytest fixtures for the carrier interconnection access billing suite.

The server is restarted with an empty database before every test, so no fixture
here may assume state survives from a previous test: each test builds everything
it needs from scratch through the live API.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import api_client  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    access_billing_analyst_headers,
    dispute_resolution_officer_headers,
    interconnection_manager_headers,
    make_carrier_representative_headers,
    network_planner_headers,
    platform_admin_headers,
    regulatory_affairs_specialist_headers,
    revenue_assurance_controller_headers,
)


@pytest.fixture(scope="session")
def api():
    """The API client bound to the service under test."""
    return api_client


@pytest.fixture
def admin_headers():
    """PlatformAdmin identity headers."""
    return platform_admin_headers()


@pytest.fixture
def manager_headers():
    """InterconnectionManager identity headers (the CLEC side of a negotiation)."""
    return interconnection_manager_headers()


@pytest.fixture
def planner_headers():
    """NetworkPlanner identity headers."""
    return network_planner_headers()


@pytest.fixture
def analyst_headers():
    """AccessBillingAnalyst identity headers; this identity issues invoices."""
    return access_billing_analyst_headers()


@pytest.fixture
def officer_headers():
    """DisputeResolutionOfficer identity headers."""
    return dispute_resolution_officer_headers()


@pytest.fixture
def regulator_headers():
    """RegulatoryAffairsSpecialist identity headers."""
    return regulatory_affairs_specialist_headers()


@pytest.fixture
def controller_headers():
    """RevenueAssuranceController identity headers."""
    return revenue_assurance_controller_headers()


@pytest.fixture
def carrier_rep_headers():
    """Builder for CarrierRepresentative headers: the acting id IS the carrier id."""
    return make_carrier_representative_headers
