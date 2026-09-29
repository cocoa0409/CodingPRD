"""Shared pytest fixtures for the compliance suite.

The harness restarts the API server against an empty database before every
single test, so no fixture here does any cleanup: each test builds the world it
needs from the program's own endpoints.
"""
import pytest

from test_helpers.api_client import ApiClient


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the API under test."""
    return ApiClient()
