"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle (start/stop/restart-before-every-test) is owned by
prd-bench-local-runner; these fixtures only wire the shared client and role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]


@pytest.fixture
def stylist_headers():
    return TEST_USERS["stylist_headers"]
