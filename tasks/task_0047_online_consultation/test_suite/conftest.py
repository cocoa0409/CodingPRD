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
def admin_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


# --- Fallback headers for entity-backed roles -----------------------------
# Use only on tests that do NOT exercise an ownership comparison (RBAC
# role mismatch, ERR_NOT_FOUND on missing entity, ERR_AUTH_MISSING).
@pytest.fixture
def patient_headers_fallback():
    return TEST_USERS["patient_headers"]


@pytest.fixture
def doctor_headers_fallback():
    return TEST_USERS["doctor_headers"]


@pytest.fixture
def pharmacist_headers_fallback():
    return TEST_USERS["pharmacist_headers"]
