"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, injects API_BASE_URL,
and restarts the API server (fresh DB, clock reset to 2026-07-01) before every
individual test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def pos_terminal_headers():
    return TEST_USERS["pos_terminal_headers"]


@pytest.fixture
def fraud_analyst_headers():
    return TEST_USERS["fraud_analyst_headers"]


@pytest.fixture
def settlement_officer_headers():
    return TEST_USERS["settlement_officer_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]


@pytest.fixture
def merchant_admin_headers():
    """Shared MerchantAdmin fallback (unowned) — only for non-ownership tests."""
    return TEST_USERS["merchant_admin_headers"]
