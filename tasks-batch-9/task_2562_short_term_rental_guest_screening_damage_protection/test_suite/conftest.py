"""Fixtures shared by every test module in this suite.

The helper package sits one directory up, so it is put on the import path here
rather than in each test file. Importing it also registers the error-to-status
map, which is why ``validate_error`` can cross-check HTTP status codes.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient, TEST_USERS  # noqa: E402


@pytest.fixture
def api():
    """A client bound to the server under test, one instance per test."""
    return ApiClient()


@pytest.fixture
def users():
    """Ready-made headers for the three opaque staff roles."""
    return TEST_USERS
