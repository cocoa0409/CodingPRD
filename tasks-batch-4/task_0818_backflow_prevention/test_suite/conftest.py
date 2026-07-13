"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, restarts the server before
every test (empty DB, logical clock at 2026-03-01T00:00:00Z), and injects API_BASE_URL.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, NO_AUTH_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def owner_headers():
    return TEST_USERS["owner_headers"]


@pytest.fixture
def tester_headers():
    return TEST_USERS["tester_headers"]


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
