"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle (start/stop/restart-before-each-test) is owned by
prd-bench-local-runner; these fixtures only wire the API client and role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, NO_AUTH_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
