"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets API_BASE_URL and PYTHONPATH and manages server lifecycle
(restarting the server before every test). These fixtures just wire up the
shared client and role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def chef_headers():
    """Shared Chef headers — for non-ownership tests only (see test_helpers/test_users.py)."""
    return TEST_USERS["chef_headers"]


@pytest.fixture
def client_headers():
    """Shared Client headers — for non-ownership tests only."""
    return TEST_USERS["client_headers"]


@pytest.fixture
def admin_headers():
    """PlatformAdmin headers (opaque identity)."""
    return TEST_USERS["admin_headers"]
