"""Shared pytest wiring for the exhibit design and fabrication suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402


@pytest.fixture
def api():
    """A client bound to the API under test.

    The harness restarts the server before each test, so every test opens on an
    empty database with the logical clock at its documented default.
    """
    return ApiClient()
