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
    """Reset in-memory server state before every test so the logical
    clock and any per-day Certificate sequence counter start fresh.
    /_test/reset is a test-only hook (not part of the PRD)."""
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
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def platform_admin_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


@pytest.fixture
def certificate_officer_headers():
    return TEST_USERS["certificate_officer_headers"]


@pytest.fixture
def certificate_officer_headers_alt():
    return TEST_USERS["certificate_officer_headers_alt"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def applicant_headers_alt():
    return TEST_USERS["applicant_headers_alt"]


# --- Fallback headers for entity-backed roles ---
# Use only for ERR_AUTH_MISSING / ERR_FORBIDDEN / ERR_NOT_FOUND on a
# missing path-parameter resource where no ownership comparison fires.
@pytest.fixture
def catalog_manager_headers_fallback():
    return TEST_USERS["catalog_manager_headers"]


@pytest.fixture
def reviewer_headers_fallback():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def lead_reviewer_headers_fallback():
    return TEST_USERS["lead_reviewer_headers"]
