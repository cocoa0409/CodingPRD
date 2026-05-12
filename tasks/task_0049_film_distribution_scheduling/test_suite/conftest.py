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
    """Reset in-memory server state before every test so each test starts
    from a clean slate. /_test/reset is a test-only hook on the server
    (not part of PRD)."""
    try:
        api_client._request(
            "POST", "/_test/reset", None,
            TEST_USERS["platform_admin_headers"],
        )
    except Exception:
        pass
    yield


# --- Opaque-role headers (PRD §2.1) ---------------------------------------
@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def ticketing_headers():
    return TEST_USERS["ticketing_platform_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_ops_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


# --- Fallback headers for entity-backed roles -----------------------------
# Use only on tests that do NOT exercise an ownership comparison
# (RBAC ERR_ROLE_FORBIDDEN, ERR_NOT_FOUND, ERR_AUTH_HEADERS_MISSING).
@pytest.fixture
def distributor_ops_fallback_headers():
    return TEST_USERS["distributor_ops_headers"]


@pytest.fixture
def cinema_ops_fallback_headers():
    return TEST_USERS["cinema_ops_headers"]
