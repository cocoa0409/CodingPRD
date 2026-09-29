"""Shared pytest fixtures for the Public Art Conservation API suite.

The server is restarted before every individual test, so each test starts
against an empty register and a logical clock pinned at its declared default.
Every piece of state a test needs is therefore built inside that test through
the documented endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402
from test_helpers.test_users import TEST_USERS  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the API under test."""
    return ApiClient()


@pytest.fixture
def users() -> dict:
    """Pre-built headers for the roles that carry an opaque operator identifier."""
    return TEST_USERS
