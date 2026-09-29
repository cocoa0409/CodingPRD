"""
Shared pytest fixtures for the County Land Bank Authority test suite.

Every test runs against a freshly launched server with an empty database, so
there is nothing to tear down: each test builds exactly the state it needs
through the API's own endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402
from test_helpers.constants import DEFAULT_CLOCK  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """An HTTP client bound to the API under test."""
    return ApiClient()


@pytest.fixture
def clock_start() -> str:
    """
    The logical UTC instant every test starts from. The server never reads
    wall-clock time, so this value is stable across runs.
    """
    return DEFAULT_CLOCK
