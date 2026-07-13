"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/health) is owned by prd-bench-local-runner; these
fixtures only wire up the already-running server's client and role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The runner restarts the server before each test."""
    return api_client


@pytest.fixture
def account_manager_headers():
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def warehouse_headers():
    return TEST_USERS["warehouse_headers"]


@pytest.fixture
def buyer_headers():
    return TEST_USERS["buyer_headers"]
