"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    GROUP_SALES_AGENT,
    GROUP_SALES_AGENT_2,
    GROUP_SALES_AGENT_3,
    PORT_OPS_COORDINATOR,
    RESERVATION_AGENT,
    REVENUE_MANAGER,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def revenue_manager():
    """Headers for a RevenueManager: pricing, allotments, promotions, settlement."""
    return REVENUE_MANAGER


@pytest.fixture
def reservation_agent():
    """Headers for a ReservationAgent: guests, bookings, payments, guarantees."""
    return RESERVATION_AGENT


@pytest.fixture
def group_sales_agent():
    """Headers for the GroupSalesAgent who creates a block."""
    return GROUP_SALES_AGENT


@pytest.fixture
def second_group_sales_agent():
    """A distinct GroupSalesAgent identifier, needed for the four-eyes signature."""
    return GROUP_SALES_AGENT_2


@pytest.fixture
def third_group_sales_agent():
    """A third distinct GroupSalesAgent identifier."""
    return GROUP_SALES_AGENT_3


@pytest.fixture
def port_ops_coordinator():
    """Headers for a PortOpsCoordinator: itinerary changes and their publication."""
    return PORT_OPS_COORDINATOR
