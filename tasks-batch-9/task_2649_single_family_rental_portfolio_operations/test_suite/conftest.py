"""Shared pytest wiring for the Single-Family Rental Portfolio Operations suite.

The harness owns the server lifecycle and restarts the service before every test, so the
only shared state a test needs is a client pointed at ``API_BASE_URL``.  Every test builds
its own preconditions from an empty database through the public API.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402


@pytest.fixture()
def api():
    """A fresh API client for one test."""
    return ApiClient()
