"""
Shared pytest fixtures.

The server is restarted and its database emptied before every individual test,
so every fixture here is function-scoped and builds its state from scratch
through the public endpoints.
"""

import pytest

from test_helpers.api_client import ApiClient
from test_helpers.constants import CLOCK_NOON
from test_helpers.fixtures import pin_clock


@pytest.fixture()
def api() -> ApiClient:
    """A client bound to the API under test."""
    return ApiClient()


@pytest.fixture()
def clock(api: ApiClient) -> str:
    """Pin the logical clock to a known instant before the scenario starts."""
    pin_clock(api, CLOCK_NOON)
    return CLOCK_NOON
