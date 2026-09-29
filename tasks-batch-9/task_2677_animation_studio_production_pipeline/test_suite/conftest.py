"""Shared pytest fixtures for the Studio Production Pipeline suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: E402,F401  (registers the error/status map)
from test_helpers.api_client import ApiClient  # noqa: E402


@pytest.fixture
def client() -> ApiClient:
    """A client bound to the server under test."""
    return ApiClient()
