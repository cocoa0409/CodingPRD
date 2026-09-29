"""Pytest bridge to the generated test helpers."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient, TEST_USERS, api_client  # noqa: E402,F401


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The shared API client; the server is restarted with an empty database
    before every test, so no per-test cleanup is required."""
    return api_client
