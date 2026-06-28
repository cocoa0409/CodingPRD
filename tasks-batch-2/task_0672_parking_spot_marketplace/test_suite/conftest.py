"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; this file only wires fixtures.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def host_headers():
    """Shared Host header — for non-ownership tests only (403/404/400)."""
    return TEST_USERS["host_headers"]


@pytest.fixture
def driver_headers():
    """Shared Driver header — for non-ownership tests only (403/404/400)."""
    return TEST_USERS["driver_headers"]


@pytest.fixture
def admin_headers():
    """PlatformAdmin header (opaque identity)."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def anonymous_headers():
    """Anonymous header (registration + clock)."""
    return TEST_USERS["anonymous_headers"]
