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
    """Reset the in-memory server state before every test so each test
    starts from a clean slate. /_test/reset is a server-side test hook
    not covered by PRD; if the implementation does not implement it,
    tests share state and any overlap surfaces as failures."""
    try:
        api_client._request(
            "POST", "/_test/reset", None,
            TEST_USERS["planner_headers"],
        )
    except Exception:
        pass
    yield


# --- Opaque-role headers (PRD §2.1) ----------------------------------------
@pytest.fixture
def planner_headers():
    return TEST_USERS["planner_headers"]


@pytest.fixture
def planner_headers_alt():
    return TEST_USERS["planner_headers_alt"]


@pytest.fixture
def planner_headers_third():
    return TEST_USERS["planner_headers_third"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def auditor_headers_alt():
    return TEST_USERS["auditor_headers_alt"]


@pytest.fixture
def couple_headers():
    return TEST_USERS["couple_headers"]


# --- Fallback for entity-backed VendorRep ---------------------------------
# Use only on tests that do NOT exercise an ownership comparison
# (e.g., role-not-authorized RBAC, ERR_VENDOR_NOT_FOUND with NON_EXISTENT_UUID).
@pytest.fixture
def vendor_rep_headers_fallback():
    return TEST_USERS["vendor_rep_headers_fallback"]
