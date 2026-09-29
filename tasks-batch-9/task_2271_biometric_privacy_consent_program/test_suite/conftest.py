"""Shared pytest wiring for the biometric privacy consent API suite.

The runner owns the server lifecycle and restarts it before every individual
test, so each test builds the state it needs from an empty database and against
the default logical clock of ``2026-08-01T00:00:00Z``.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the API under test."""
    return ApiClient()
