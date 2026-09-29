"""Pytest fixtures exposing the test_helpers infrastructure.

The harness restarts the server and empties the database before every single
test, so no fixture here may cache domain state — only the stateless client and
the pre-built role headers.
"""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def slot_coordinator_headers():
    return TEST_USERS["slot_coordinator_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def filing_agent_headers():
    return TEST_USERS["filing_agent_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def second_filing_agent_headers():
    return TEST_USERS["second_filing_agent_headers"]


@pytest.fixture
def second_slot_coordinator_headers():
    return TEST_USERS["second_slot_coordinator_headers"]


@pytest.fixture
def network_planner_headers():
    """Fallback NetworkPlanner identity, for calls that never reach an
    ownership check."""
    return TEST_USERS["network_planner_headers"]


@pytest.fixture
def partner_carrier_headers():
    """Fallback PartnerCarrier identity, for calls that never reach an
    ownership check."""
    return TEST_USERS["partner_carrier_headers"]
