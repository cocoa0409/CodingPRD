"""Shared pytest fixtures for the festival talent-buying compliance suite.

The harness restarts the API server before every individual test, so the
database is empty at the start of each test and every fixture below builds its
preconditions from scratch through the public API.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """HTTP client pointed at the server under test."""
    return ApiClient()


@pytest.fixture
def clock(api) -> str:
    """Logical clock parked at the default instant."""
    fx.set_clock(api)
    return "2026-08-01T00:00:00Z"


@pytest.fixture
def edition(api):
    """Allocated single-tier edition with one flagship stage and one act."""
    return fx.single_tier_edition(api)


@pytest.fixture
def three_tier_edition(api):
    """Allocated edition whose tiers split the allocatable budget 50/30/20."""
    return fx.three_tier_edition(api)


@pytest.fixture
def accepted_booking(api, edition):
    """One accepted booking on the single-tier edition."""
    return fx.accepted_booking(api, edition)


@pytest.fixture
def countersigned_booking(api, edition):
    """One booking taken all the way to COUNTERSIGNED."""
    return fx.countersigned_booking(api, edition)
