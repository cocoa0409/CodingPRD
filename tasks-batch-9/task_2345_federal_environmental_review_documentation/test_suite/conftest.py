"""Shared pytest configuration for the Federal Environmental Review API suite.

The harness restarts the API server before every individual test, so each test
starts against an empty database and builds every precondition it needs through
the endpoints the PRD declares.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_client  # noqa: E402


@pytest.fixture
def client():
    """The shared API client, pointed at the base URL the harness exports."""
    return api_client
