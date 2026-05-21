"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires the session-scoped API client and per-role header fixtures.

PRD §2.1 identity rules:
- Commissioner is OPAQUE — the shared TEST_USERS constant is canonical.
- Manager (X-User-ID == Team.manager_user_id) is ENTITY-BACKED — tests
  that exercise ownership MUST mint headers via
  make_manager_headers(team["manager_user_id"]) and NEVER fall back to
  the manager_fallback_headers fixture.
"""
from __future__ import annotations

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle owned by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    """Best-effort wipe of the implementation's in-memory store between
    tests. Implementations that do not expose /__test__/reset are
    tolerated; tests still pass as long as they create unique entities.
    """
    try:
        api_client._request("POST", "/__test__/reset", None, {})
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — shared constants are canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def commissioner_headers():
    return TEST_USERS["commissioner_headers"]


@pytest.fixture
def commissioner_headers_alt():
    return TEST_USERS["commissioner_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed fallback — ONLY for tests that do not exercise
# ownership (PRD §2.1). Ownership-gated calls mint per-instance
# headers via make_manager_headers(team["manager_user_id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def manager_fallback_headers():
    return TEST_USERS["manager_headers"]
