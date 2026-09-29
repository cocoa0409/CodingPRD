"""
Shared pytest fixtures for the Wholesaling Assignment Desk acceptance suite.

The harness relaunches the API server before every individual test, so each
test begins against an empty database with the logical clock back at its fresh
value of 2026-08-01T00:00:00Z. Every scenario is therefore constructed inside
the test through the API's own endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the API under test."""
    return ApiClient()
