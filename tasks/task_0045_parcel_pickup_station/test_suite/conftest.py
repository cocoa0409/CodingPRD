"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start, readiness, shutdown) is managed by the
prd-bench-local-runner framework. PYTHONPATH points at the parent
directory so `test_helpers` is importable directly.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Base URL supplied by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_server_state():
    """Reset in-memory server state before every test so that the
    logical clock, in-memory ids and counters all start clean. The
    /_test/reset endpoint is a test-only hook (not part of PRD)."""
    try:
        api_client._request(
            "POST", "/_test/reset", None,
            TEST_USERS["platform_admin_headers"],
        )
    except Exception:
        pass
    yield


# --- Opaque-role headers (PRD §2.1) ----------------------------------------
@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def platform_admin_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


@pytest.fixture
def recipient_headers():
    return TEST_USERS["recipient_headers"]


@pytest.fixture
def recipient_headers_alt():
    return TEST_USERS["recipient_headers_alt"]


@pytest.fixture
def courier_company_headers():
    return TEST_USERS["courier_company_headers"]


@pytest.fixture
def payment_system_headers():
    return TEST_USERS["payment_system_headers"]


# --- Fallback headers for entity-backed Manager / Clerk roles --------------
# Use only on tests that do NOT exercise an ownership comparison
# (ERR_AUTH_MISSING, ERR_FORBIDDEN, ERR_RESOURCE_NOT_FOUND on a
# nonexistent path, ERR_VALIDATION on a missing/invalid payload).
@pytest.fixture
def manager_headers_fallback():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def clerk_headers_fallback():
    return TEST_USERS["clerk_headers"]
