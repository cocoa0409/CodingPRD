"""Shared pytest fixtures for the marketing-mix modelling compliance suite.

The harness relaunches the API against an empty database before every single
test, so no fixture may rely on state another test left behind. Every helper in
`test_helpers.fixtures` therefore builds its whole precondition chain from
scratch through the declared endpoints.
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
