"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle — this conftest just wires up
fixtures so tests can request headers by role without importing test_helpers in
each file.
"""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


# ──────────────── Opaque-role headers (PRD §2.1) ────────────────


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_headers_alt():
    return TEST_USERS["admin_headers_alt"]


@pytest.fixture
def receptionist_headers():
    return TEST_USERS["receptionist_headers"]


@pytest.fixture
def billing_officer_headers():
    return TEST_USERS["billing_officer_headers"]


@pytest.fixture
def payment_clerk_headers():
    return TEST_USERS["payment_clerk_headers"]


# ──────────────── Entity-backed fallbacks (non-ownership tests only) ────────────────


@pytest.fixture
def tenant_admin_headers_fallback():
    return TEST_USERS["tenant_admin_headers_fallback"]


@pytest.fixture
def tenant_member_headers_fallback():
    return TEST_USERS["tenant_member_headers_fallback"]
