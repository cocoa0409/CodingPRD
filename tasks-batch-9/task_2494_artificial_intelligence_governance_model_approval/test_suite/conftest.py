"""Pytest fixtures exposing the shared test infrastructure.

The runner restarts the API server with an empty database before every single
test, so no fixture here may cache domain data across tests — only the HTTP
client itself is shared.
"""

import pytest

from test_helpers import ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client
