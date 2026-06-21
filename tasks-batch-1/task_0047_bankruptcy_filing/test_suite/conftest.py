"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and manages server
lifecycle (the server is restarted before every test, so each test starts
against an empty database).
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
def debtor_headers():
    return TEST_USERS["debtor_headers"]


@pytest.fixture
def creditor_headers():
    return TEST_USERS["creditor_headers"]


@pytest.fixture
def trustee_headers():
    return TEST_USERS["trustee_headers"]
