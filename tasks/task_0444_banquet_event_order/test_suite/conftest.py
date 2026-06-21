"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (so `test_helpers` is importable) and the server
lifecycle (it restarts the server before every test). These fixtures only wire
the client and role headers into pytest.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS, UNKNOWN_ROLE_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def sales_headers():
    return TEST_USERS["sales_manager_headers"]


@pytest.fixture
def captain_headers():
    return TEST_USERS["banquet_captain_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["accounting_clerk_headers"]


@pytest.fixture
def unknown_role_headers():
    return UNKNOWN_ROLE_HEADERS
