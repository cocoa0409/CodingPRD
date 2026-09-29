"""Shared pytest fixtures for the correctional food service compliance suite.

The harness relaunches the API against an empty database before every single
test, so no fixture may assume state left behind by another test.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the API under test."""
    return ApiClient()
