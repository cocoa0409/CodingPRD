"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/health) is owned by prd-bench-local-runner; these
fixtures only wire up the already-running client and role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def staff_headers():
    return TEST_USERS["staff_headers"]


@pytest.fixture
def public_headers():
    return TEST_USERS["public_headers"]


@pytest.fixture
def member_headers():
    """Fallback Member headers — use only for non-ownership tests."""
    return TEST_USERS["member_headers"]
