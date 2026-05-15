"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest only
wires per-role headers and the session-scoped api client.

PRD §2.1 identity rules:
- LabClerk and LabManager are OPAQUE → shared constants are canonical.
- Tester / Reviewer / Signatory are entity_backed → every ownership-
  gated test MUST use make_<role>_headers(entity['id']).
"""
from __future__ import annotations
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle managed by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_server_state_per_test():
    """Reset in-memory server state before each test for full isolation.

    The PRD-required selector (PRD §3.3) ranks testers globally across all
    rows present in the server. To make per-test claims like "the freshly
    created tester is auto-assigned" deterministic, each test starts with
    an empty DB.
    """
    try:
        api_client.session.post(f"{api_client.base_url}/_test/reset", timeout=5)
    except Exception:
        # If the reset endpoint isn't available, fall through silently.
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers (canonical via shared constants)
# ---------------------------------------------------------------------------
@pytest.fixture
def lab_clerk_headers():
    return TEST_USERS["lab_clerk_headers"]


@pytest.fixture
def lab_clerk_headers_alt():
    return TEST_USERS["lab_clerk_headers_alt"]


@pytest.fixture
def lab_manager_headers():
    return TEST_USERS["lab_manager_headers"]


@pytest.fixture
def lab_manager_headers_alt():
    return TEST_USERS["lab_manager_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed fallback headers — use ONLY for tests that don't exercise
# ownership (missing-auth, wrong-role, missing-resource).
# ---------------------------------------------------------------------------
@pytest.fixture
def tester_fallback_headers():
    """PRD §2.1: real Tester X-User-ID must equal Tester.id; this constant
    matches no real tester, so use it only for tests that do NOT exercise
    ownership."""
    return TEST_USERS["tester_headers"]


@pytest.fixture
def reviewer_fallback_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def signatory_fallback_headers():
    return TEST_USERS["signatory_headers"]
