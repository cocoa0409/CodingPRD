"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def agent_headers():
    """ProvisioningAgent — sales and provisioning operator."""
    return TEST_USERS["provisioning_agent_headers"]


@pytest.fixture
def second_agent_headers():
    """A second ProvisioningAgent identity, for two-operator workflows."""
    return TEST_USERS["provisioning_agent_2_headers"]


@pytest.fixture
def netops_headers():
    """NetworkOpsEngineer — capacity, metering and impairment events."""
    return TEST_USERS["network_ops_engineer_headers"]


@pytest.fixture
def compliance_headers():
    """ComplianceOfficer — licences, roaming decisions and credit decisions."""
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def second_compliance_headers():
    """A second ComplianceOfficer identity, for the segregation-of-duties rule."""
    return TEST_USERS["compliance_officer_2_headers"]


@pytest.fixture
def logistics_headers():
    """LogisticsCoordinator — terminal shipping, returns and warranty RMAs."""
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def subscriber_headers():
    """Shared Subscriber constant.

    Subscriber identity is entity backed, so this is safe only for calls that
    never reach an ownership comparison. Anything ownership-gated must use
    make_subscriber_headers(subscriber_id).
    """
    return TEST_USERS["subscriber_headers"]
