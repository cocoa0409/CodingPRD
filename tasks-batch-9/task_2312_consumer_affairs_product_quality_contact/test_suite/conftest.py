"""Shared pytest fixtures for the suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient, api_client  # noqa: E402


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API under test."""
    return api_client
