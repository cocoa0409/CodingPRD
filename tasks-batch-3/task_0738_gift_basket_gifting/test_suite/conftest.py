"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, injects API_BASE_URL,
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
def finance_headers():
    return TEST_USERS["finance_approver_headers"]


@pytest.fixture
def proof_headers():
    return TEST_USERS["proof_approver_headers"]


@pytest.fixture
def warehouse_headers():
    return TEST_USERS["warehouse_ops_headers"]


@pytest.fixture
def shipping_headers():
    return TEST_USERS["shipping_ops_headers"]


@pytest.fixture
def account_manager_headers():
    """Shared AccountManager constant — for non-ownership probes only. Ownership-gated
    tests build per-account headers via make_account_manager_headers(id)."""
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
