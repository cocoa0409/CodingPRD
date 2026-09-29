"""Shared pytest fixtures for the Prior Learning Assessment suite.

The harness restarts the service before every individual test, so each test
starts against an empty database and builds every precondition it needs through
the endpoints PRD S4 declares.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import PlaApiClient  # noqa: E402
from test_helpers import api_errors  # noqa: E402,F401  (registers the error->status map)


@pytest.fixture
def client() -> PlaApiClient:
    """A client pointed at the service under test."""
    return PlaApiClient()
