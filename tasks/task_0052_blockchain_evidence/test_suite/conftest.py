"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires per-role headers and the session-scoped api client.
"""
from __future__ import annotations
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# ---------------------------------------------------------------------------
# Role-header fixtures. Per PRD §2.1, Customer is entity_backed and
# ownership-gated; tests that exercise ownership MUST use the per-instance
# builder make_customer_headers(customer['id']). These fixtures are only
# safe for tests that do NOT depend on Customer ownership matching.
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def admin_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


@pytest.fixture
def notary_headers():
    return TEST_USERS["notary_officer_headers"]


@pytest.fixture
def judicial_headers():
    return TEST_USERS["judicial_officer_headers"]


@pytest.fixture
def judicial_headers_alt():
    return TEST_USERS["judicial_officer_headers_alt"]


@pytest.fixture
def customer_headers():
    """Fallback Customer headers — opaque X-User-ID 'customer-fallback'.

    PRD §2.1: ownership-gated Customer-role endpoints compare X-User-ID
    to the resource's customer_id; this constant matches no real
    Customer.id, so use it only for tests that do NOT exercise ownership
    (missing-auth, wrong-role, missing-resource scenarios).
    """
    return TEST_USERS["customer_headers"]
