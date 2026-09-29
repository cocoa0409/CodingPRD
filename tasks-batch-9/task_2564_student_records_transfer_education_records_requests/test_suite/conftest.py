"""Shared pytest fixtures for the suite.

The server and its database are relaunched before every test, so no fixture
here may assume any state left behind by another test.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_client  # noqa: E402


@pytest.fixture
def api():
    """The API client, already carrying the `/records-office` prefix."""
    return api_client
