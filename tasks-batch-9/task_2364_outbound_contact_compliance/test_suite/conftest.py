"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    ComplianceWorld,
    TEST_USERS,
    api_client,
    make_campaign_manager_headers,
    make_compliance_officer_headers,
    make_consumer_headers,
    make_dialer_operator_headers,
    make_platform_admin_headers,
)
from test_helpers.fixtures import DEFAULT_CLOCK


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def world(api: ApiClient) -> ComplianceWorld:
    """Builder over the documented endpoints, against a freshly emptied database."""
    return ComplianceWorld(api)


@pytest.fixture
def clocked_world(world: ComplianceWorld) -> ComplianceWorld:
    """Builder whose logical clock already sits on the canonical working instant."""
    world.set_clock(DEFAULT_CLOCK)
    return world


@pytest.fixture
def draft_campaign(world: ComplianceWorld):
    """Full precondition chain with the campaign still in DRAFT."""
    return world.build(stop_after="campaign")


@pytest.fixture
def scrubbed_campaign(world: ComplianceWorld):
    """Full precondition chain with a completed scrub, awaiting certification."""
    return world.build(stop_after="scrub")


@pytest.fixture
def active_campaign(world: ComplianceWorld):
    """Full precondition chain with the campaign running."""
    return world.build(stop_after="launch")


# ---------------------------------------------------------------------------
# One header fixture per role
# ---------------------------------------------------------------------------


@pytest.fixture
def platform_admin_headers():
    """Headers for a PlatformAdmin."""
    return make_platform_admin_headers()


@pytest.fixture
def campaign_manager_headers():
    """Headers for a CampaignManager."""
    return make_campaign_manager_headers()


@pytest.fixture
def compliance_officer_headers():
    """Headers for a ComplianceOfficer."""
    return make_compliance_officer_headers()


@pytest.fixture
def dialer_operator_headers():
    """Headers for a DialerOperator."""
    return make_dialer_operator_headers()


@pytest.fixture
def consumer_headers_for():
    """Factory returning Consumer headers for a given contact identifier."""
    return make_consumer_headers


@pytest.fixture
def test_users():
    """The role/identity matrix used across the suite."""
    return TEST_USERS
