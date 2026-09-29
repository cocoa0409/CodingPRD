"""Shared pytest fixtures for the leak-detection API suite.

The harness restarts the server before every individual test, so each test opens
against an empty database and a logical clock reading its startup default.  Every
precondition a test needs is therefore built through the documented endpoints
inside the test itself.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402
from test_helpers.test_users import TEST_USERS  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    return ApiClient()


@pytest.fixture
def users() -> dict:
    return TEST_USERS
