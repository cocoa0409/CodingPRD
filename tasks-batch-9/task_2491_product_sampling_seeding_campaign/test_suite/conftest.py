"""Shared fixtures for the sampling and seeding test suite."""

import pytest

from test_helpers import (
    SamplingApiClient,
    anonymous_headers,
    campaign_manager_headers,
    fulfillment_ops_headers,
    moderator_a_headers,
    moderator_b_headers,
    platform_admin_headers,
)
from test_helpers.constants import CLOCK_EPOCH


@pytest.fixture(scope="session")
def api() -> SamplingApiClient:
    """HTTP client pointed at the server under test."""
    return SamplingApiClient()


@pytest.fixture(autouse=True)
def pinned_clock(api: SamplingApiClient):
    """Place the logical clock at its documented startup instant.

    The clock already begins at this instant, so this only guarantees that a
    test never inherits a repositioned clock. Repositioning mutates no entity.
    """
    api.set_clock(platform_admin_headers(), CLOCK_EPOCH)
    return CLOCK_EPOCH


@pytest.fixture
def manager():
    """Headers for a CampaignManager caller."""
    return campaign_manager_headers()


@pytest.fixture
def moderator():
    """Headers for the first ComplianceModerator identity."""
    return moderator_a_headers()


@pytest.fixture
def second_moderator():
    """Headers for a second, distinct ComplianceModerator identity."""
    return moderator_b_headers()


@pytest.fixture
def ops():
    """Headers for a FulfillmentOps caller."""
    return fulfillment_ops_headers()


@pytest.fixture
def admin():
    """Headers for a PlatformAdmin caller."""
    return platform_admin_headers()


@pytest.fixture
def anonymous():
    """Headers for an Anonymous caller."""
    return anonymous_headers()
