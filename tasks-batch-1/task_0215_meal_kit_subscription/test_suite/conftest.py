"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (test_helpers importable) and the server lifecycle (restarted
to an empty DB before every test). These fixtures only wire up the shared client and headers.
"""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_member_headers, make_admin_headers, make_ops_headers, make_anonymous_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]


@pytest.fixture
def anon_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def member_headers():
    """Shared Member headers — only for non-ownership tests. For ownership-gated calls use
    make_member_headers(member_id) with the real member id."""
    return TEST_USERS["member_headers"]
