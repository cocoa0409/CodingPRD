"""Shared pytest fixtures for the Insurance Premium Finance compliance suite.

The harness owns the server lifecycle and publishes `API_BASE_URL`, and it
restarts the API before every individual test, so each test starts against an
empty database and builds every precondition it needs through declared
endpoints only.
"""

import pytest

from test_helpers import ApiClient


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the base URL the harness published."""
    return ApiClient()
