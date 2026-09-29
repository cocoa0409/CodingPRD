"""Pytest wiring shared by every test module in this suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.test_users import TEST_USERS  # noqa: E402


@pytest.fixture
def api():
    """A client pointed at the service under test.

    The harness restarts the service before each test, so every test begins
    against empty storage with the logical clock at its process-start value.
    """
    return ApiClient()


@pytest.fixture
def users():
    """Pre-built headers for the roles whose identifier is opaque."""
    return TEST_USERS
