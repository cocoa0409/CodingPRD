"""Pytest fixtures exposing test_helpers infrastructure.

The runner restarts the server before every test (empty DB) and provides
API_BASE_URL, so the client is function-scoped and every test builds its own
state from scratch.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402


@pytest.fixture
def client():
    return ApiClient()
