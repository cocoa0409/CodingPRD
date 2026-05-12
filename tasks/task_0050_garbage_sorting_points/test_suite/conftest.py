"""Pytest fixtures exposing test_helpers infrastructure to test_suite."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped ApiClient. The server lifecycle is owned by the
    prd-bench-local-runner; this client just speaks HTTP to API_BASE_URL."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_server_state():
    """Reset in-memory server state before every test so each test starts
    from a clean slate. /_test/reset is a test-only hook on the server
    (not part of PRD)."""
    try:
        api_client._request("POST", "/_test/reset", None, {})
    except Exception:
        pass
    yield


# --- Opaque-role header fixtures (safe to share across tests) ---
@pytest.fixture
def system_operator_headers():
    return TEST_USERS["system_operator_headers"]


@pytest.fixture
def community_admin_headers():
    return TEST_USERS["community_admin_headers"]


@pytest.fixture
def appeal_reviewer_headers():
    return TEST_USERS["appeal_reviewer_headers"]


# --- Entity-backed Resident fallback (do NOT use for ownership-gated calls) ---
@pytest.fixture
def resident_fallback_headers():
    """Shared Resident-role headers with a synthetic X-User-ID. Use ONLY for
    tests that do not exercise ownership checks (e.g., RBAC permission
    denied, malformed payload, or 404 on missing path). Ownership-gated
    Resident calls MUST go through make_resident_headers(resident['id'])."""
    return TEST_USERS["resident_fallback_headers"]
