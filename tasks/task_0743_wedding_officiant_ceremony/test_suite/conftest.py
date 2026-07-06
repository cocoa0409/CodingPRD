"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner sets PYTHONPATH so test_helpers is importable, injects
API_BASE_URL, and restarts the server (empty database) before every test.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]
