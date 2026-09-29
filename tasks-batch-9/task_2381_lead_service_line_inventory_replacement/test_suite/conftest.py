"""Shared pytest wiring for the Lead Service Line Inventory & Replacement suite.

The harness relaunches the service before every individual test, so each test
starts against an empty store with the logical clock parked at
``2026-08-01T00:00:00Z``. There is therefore nothing to tear down here; the only
shared object is the HTTP client itself.
"""

import pytest

from test_helpers import ApiClient


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the base URL the runner exported."""
    return ApiClient()
