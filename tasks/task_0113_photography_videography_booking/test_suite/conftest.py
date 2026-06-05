"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH so test_helpers is importable, and manages server
lifecycle (the server is rebooted and the database emptied before every test).
"""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    ANONYMOUS_HEADERS, NO_AUTH_HEADERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]


@pytest.fixture
def photographer_headers():
    return TEST_USERS["photographer_headers"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
