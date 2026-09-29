"""Shared pytest configuration for the Regional CPA Settlement suite.

The harness restarts the service before each test, so every test opens against an
empty store whose logical clock reads 2026-08-01T00:00:00Z and builds all of its
preconditions through the public endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import CpaApiClient  # noqa: E402
from test_helpers.api_errors import register_error_status_map  # noqa: E402


@pytest.fixture(autouse=True, scope="session")
def error_status_map():
    """Teach the validators which HTTP status belongs to each error identifier."""
    register_error_status_map()


@pytest.fixture
def api() -> CpaApiClient:
    """A domain client pointed at the service under test."""
    return CpaApiClient()
