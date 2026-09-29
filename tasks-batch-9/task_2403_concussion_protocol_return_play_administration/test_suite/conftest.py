"""
Shared pytest fixtures for the Concussion Protocol & Return-to-Play API suite.

The API server is restarted before every individual test, so each test starts
against an empty database and must build the protocol state it needs from
scratch.  Nothing here persists between tests.
"""

import pytest

from test_helpers.api_client import ApiClient


@pytest.fixture
def api() -> ApiClient:
    """Client bound to the API under test (base URL from the environment)."""
    return ApiClient()
