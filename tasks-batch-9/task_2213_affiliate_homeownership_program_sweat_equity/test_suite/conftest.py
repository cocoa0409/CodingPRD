"""Shared pytest fixtures.

The harness relaunches the service before every individual test, so each test
starts against an empty database with the logical clock at its documented
initial instant and builds every row it needs through declared endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: E402,F401  (registers the status map)
from test_helpers.api_client import HomeownershipClient  # noqa: E402


@pytest.fixture()
def api() -> HomeownershipClient:
    """Client bound to the service under test."""
    return HomeownershipClient()
