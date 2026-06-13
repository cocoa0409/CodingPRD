"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, sets API_BASE_URL,
and restarts the server (fresh empty DB) before every individual test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["store_operator_headers"]


@pytest.fixture
def anon_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def member_headers():
    """Shared Member constant — for non-ownership probes only. Ownership-gated
    tests must build per-member headers via make_member_headers(id)."""
    return TEST_USERS["member_headers"]
