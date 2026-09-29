"""Shared pytest configuration for the PRD compliance suite.

The service under test is already running and is restarted with an empty
database before each test, so no fixture here starts, stops or health-checks
it. PRD 2.10: "the server starts at the fixed default 2026-08-01T00:00:00Z and
NEVER falls back to real wall-clock time", so any test that cares about time
moves the logical clock explicitly.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client for the service under test."""
    return ApiClient()
