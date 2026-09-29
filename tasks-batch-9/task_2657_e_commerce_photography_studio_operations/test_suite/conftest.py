"""Shared pytest fixtures for the Studio Operations API compliance suite.

The harness restarts the server before every test, so the database is empty at
the start of each one: nothing here is shared state between tests, and every
fixture that needs rows creates them through the public endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the API under test."""
    return ApiClient()


@pytest.fixture
def world(api: ApiClient):
    """Reference data on a MODEL bay under the standard 2026-08-03T08:00:00Z clock."""
    return fx.build_reference_data(api)


@pytest.fixture
def still_life_world(api: ApiClient):
    """Reference data on a STILL_LIFE bench, for the flat-lay branches."""
    return fx.build_reference_data(
        api, station_type="STILL_LIFE", station_code="STILL-1"
    )
