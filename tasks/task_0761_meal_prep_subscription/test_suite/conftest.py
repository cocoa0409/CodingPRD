"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle (start/stop/restart-before-each-test) is owned by prd-bench-local-runner;
these fixtures only hand tests a ready-to-use client and pre-built role headers.
"""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_customer_headers, make_admin_headers, make_anonymous_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return make_admin_headers()


@pytest.fixture
def anonymous_headers():
    return make_anonymous_headers()


@pytest.fixture
def customer_headers():
    """Shared Customer constant — non-ownership tests only. Ownership-gated calls must build
    per-customer headers via make_customer_headers(customer_id)."""
    return TEST_USERS["customer_headers"]
