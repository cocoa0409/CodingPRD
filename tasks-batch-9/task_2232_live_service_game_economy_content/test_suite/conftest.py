"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def producer_headers():
    """ContentProducer: seasons, episode cadence and the event calendar."""
    return TEST_USERS["content_producer_headers"]


@pytest.fixture
def designer_headers():
    """EconomyDesigner: offers, disclosure tables and tuning changes."""
    return TEST_USERS["economy_designer_headers"]


@pytest.fixture
def designer_alt_headers():
    """A second EconomyDesigner, used where authorship must differ."""
    return TEST_USERS["economy_designer_alt_headers"]


@pytest.fixture
def liveops_headers():
    """LiveOpsCommander: capacity, settlements, tuning rollout and monitoring."""
    return TEST_USERS["live_ops_commander_headers"]


@pytest.fixture
def compliance_headers():
    """ComplianceOfficer: offer review, disclosure publication, refunds and spend guards."""
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_alt_headers():
    """A second ComplianceOfficer, used where the reviewer must differ."""
    return TEST_USERS["compliance_officer_alt_headers"]


@pytest.fixture
def player_headers():
    """Player headers with a placeholder identity — only for calls that never resolve ownership."""
    return TEST_USERS["player_headers"]
