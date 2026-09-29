"""Shared pytest fixtures for the glass container manufacturing suite."""

import pytest

from test_helpers import ApiClient


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the API under test.

    Each test runs against a freshly started server with an empty store, so
    every test builds the state it needs through the declared endpoints.
    """
    return ApiClient()
