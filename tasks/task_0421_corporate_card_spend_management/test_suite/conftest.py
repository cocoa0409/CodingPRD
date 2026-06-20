"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH so `test_helpers` is importable, and it manages
the server lifecycle (restart before every test). These fixtures only wire the
client and role headers into pytest.
"""
import pytest

from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_finance_admin_headers, make_approver_headers, make_cardholder_headers,
    make_auditor_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["finance_admin_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["approver_headers"]


@pytest.fixture
def cardholder_headers():
    return TEST_USERS["cardholder_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
