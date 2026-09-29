"""Shared pytest fixtures for the residency administration compliance suite.

The harness restarts the service before every individual test, so each test
begins against an empty database and every precondition is built from scratch
through the public endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the service under test."""
    return ApiClient()
