"""Shared fixtures for the DR testing and failover exercise suite.

Every test starts against a server whose database is empty, so all state used by
a test is built through the documented endpoints inside that test.
"""

import pytest

from test_helpers import ApiClient


@pytest.fixture
def api() -> ApiClient:
    """A client for the API under test."""
    return ApiClient()
