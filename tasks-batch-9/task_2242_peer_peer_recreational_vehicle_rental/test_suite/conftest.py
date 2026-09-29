"""Shared pytest wiring for the RV share marketplace suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient, api_client  # noqa: E402


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The marketplace API client, one instance per session."""
    return api_client


@pytest.fixture(autouse=True)
def _clean_connection_pool(api: ApiClient):
    """Never hand a test a socket left over from the previous server process.

    The runner restarts the API server on the same port before every test, so a
    pooled keep-alive connection is guaranteed to be stale by the time the next
    test opens.
    """
    api.reset_session()
    yield
