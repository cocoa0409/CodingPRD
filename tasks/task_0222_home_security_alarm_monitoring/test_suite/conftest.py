"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, and manages the
server lifecycle (restarting it before every individual test). These fixtures
just wire the shared client and role headers into pytest.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def subscriber_headers():
    """Shared Subscriber constant — only for non-ownership tests (forbidden /
    unauthenticated checks). Ownership-gated calls must use
    make_subscriber_headers(account_id)."""
    return TEST_USERS["subscriber_headers"]
