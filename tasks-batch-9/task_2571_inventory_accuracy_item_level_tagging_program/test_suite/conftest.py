"""
Shared pytest configuration.

The harness starts a fresh API process with an empty database before each test,
so every test builds the world it needs through the documented endpoints.
"""

import pytest

from test_helpers.api_client import ApiClient
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.test_users import ADMIN


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the API under test."""
    return ApiClient()


@pytest.fixture
def clock_at_default(api: ApiClient):
    """
    Pin the logical clock to the documented default instant.

    Tests that assert on a stamped timestamp use this so the value they compare
    against is the one the request-time clock is holding.
    """
    api.set_clock(DEFAULT_CLOCK_UTC, ADMIN)
    return DEFAULT_CLOCK_UTC
