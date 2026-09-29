"""Shared pytest fixtures for the Gift Card Fraud & Balance Protection suite.

The harness restarts the service before every test, so each test begins against
an empty database.  The one exception the PRD guarantees is the risk-policy
singleton, which "is seeded at process start with all of the defaults below, so
reading it succeeds against an empty database".
"""

import pytest

from test_helpers import GiftCardApiClient


@pytest.fixture
def client() -> GiftCardApiClient:
    """An API client bound to the service under test."""
    return GiftCardApiClient()
