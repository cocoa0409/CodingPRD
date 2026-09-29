"""
Shared pytest fixtures for the Berry Harvest Ops API compliance suite.

The harness owns the service lifecycle: it restarts the process before every
individual test, so each test opens onto an empty database and a logical clock
sitting at its start-up value. PRD section 2.5 fixes that value: "At service
start-up the logical clock reads exactly `2026-08-01T00:00:00Z`."

Consequently there is no database cleanup here and no cross-test ordering: a
test that needs a later date moves the clock itself, and a test that needs a
resource creates it.
"""

import pytest

from test_helpers import ApiClient


@pytest.fixture
def api() -> ApiClient:
    """One API client bound to the base URL the harness exported."""
    return ApiClient()
