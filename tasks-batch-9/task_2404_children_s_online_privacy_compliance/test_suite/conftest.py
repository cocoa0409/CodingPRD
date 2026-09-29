"""Shared pytest configuration for the Children's Online Privacy Compliance suite.

The server is relaunched before each test, so every test begins against an empty
database with the logical clock at its documented startup value of
`2026-08-01T00:00:00Z`. Tests therefore build their own preconditions and never
depend on ordering.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_client  # noqa: E402


@pytest.fixture
def client():
    """The API client, shared by every test."""
    return api_client
