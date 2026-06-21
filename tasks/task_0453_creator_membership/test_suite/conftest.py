"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (so `test_helpers` is importable) and the server
lifecycle (it restarts the server before every test). These fixtures only wire
the client and role headers into pytest.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def creator_headers():
    return TEST_USERS["creator_headers"]


@pytest.fixture
def patron_headers():
    return TEST_USERS["patron_headers"]
