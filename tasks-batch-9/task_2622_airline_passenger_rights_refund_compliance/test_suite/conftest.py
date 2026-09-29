"""Pytest wiring for the passenger-rights compliance suite.

The harness restarts the server before each test, so every test opens against
an empty database and a logical clock reading the mandatory startup default of
`2026-08-01T00:00:00Z` (PRD §2.8).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402


@pytest.fixture()
def api() -> ApiClient:
    """A client bound to the running instance under test."""
    return ApiClient()
