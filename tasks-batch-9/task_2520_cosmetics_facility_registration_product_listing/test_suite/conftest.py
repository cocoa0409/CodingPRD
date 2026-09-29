"""Shared pytest fixtures for the Cosmetics API compliance suite.

The harness restarts the service before every test, so each test observes an
empty database and a logical clock reading its startup default.
"""

import pytest

from test_helpers import CosmeticsApiClient


@pytest.fixture
def api() -> CosmeticsApiClient:
    """A client pointed at the service under test."""
    return CosmeticsApiClient()
