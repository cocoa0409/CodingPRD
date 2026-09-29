"""Shared pytest configuration for the residency match season test suite.

Importing :mod:`test_helpers` registers the error-id to HTTP-status map with the
shared validator layer, so ``validate_error`` checks the status code too.

The runner restarts the API with an empty store before every individual test, so
each test builds the world it needs from scratch through the public endpoints.
"""

from __future__ import annotations

import pytest

from test_helpers import ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The one HTTP client every test drives the API through."""
    return api_client
