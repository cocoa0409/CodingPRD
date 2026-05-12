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
            TEST_USERS["school_admin_headers"],
        )
    except Exception:
        pass
    yield


# --- Opaque admin role -----------------------------------------------------
@pytest.fixture
def admin_headers():
    return TEST_USERS["school_admin_headers"]


@pytest.fixture
def admin_headers_alt():
    return TEST_USERS["school_admin_headers_alt"]


# --- Fallback constants for opaque (but identity-recorded) roles.
#     Use only on tests that do NOT exercise identity comparison: i.e.,
#     RBAC ERR_FORBIDDEN, ERR_AUTH_MISSING, ERR_NOT_FOUND. For tests
#     that exercise ownership or SOD, use the per-instance builders.
@pytest.fixture
def student_headers_fallback():
    return TEST_USERS["student_headers"]


@pytest.fixture
def dept_officer_headers_fallback():
    return TEST_USERS["dept_officer_headers"]


@pytest.fixture
def finance_officer_headers_fallback():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def reviewer_headers_fallback():
    return TEST_USERS["reviewer_headers"]
