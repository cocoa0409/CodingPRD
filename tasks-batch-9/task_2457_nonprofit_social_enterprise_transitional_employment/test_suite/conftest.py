"""Shared pytest fixtures for the transitional-employment API suite.

The server is restarted before each test, so every test begins against an empty
database and builds whatever history it needs from the documented endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the running server."""
    return ApiClient()
