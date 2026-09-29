"""
Shared pytest fixtures for the Ground Lease Administration compliance suite.

The harness restarts the service before every individual test, so each test
starts against an empty database with the logical clock at its
2026-08-01T00:00:00Z default (PRD §2.5). Nothing here tears anything down.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import GroundLeaseApiClient  # noqa: E402


@pytest.fixture
def api():
    """A client bound to the service under test."""
    return GroundLeaseApiClient()
