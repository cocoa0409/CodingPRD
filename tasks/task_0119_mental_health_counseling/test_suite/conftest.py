"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- Therapist and Supervisor are ENTITY-BACKED. Tests that require
  ownership-gated behavior mint headers via make_therapist_headers(...)
  or make_supervisor_headers(...) — never the shared fallback
  constants.
- PracticeAdmin and BillingClerk are OPAQUE — shared TEST_USERS
  headers are canonical.
"""
from __future__ import annotations

import pytest

from test_helpers import ApiClient, TEST_USERS, anchor_clock, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle owned by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    """Best-effort wipe of the implementation's in-memory store between
    tests. Implementations that do not expose /__test__/reset are
    tolerated; tests still pass as long as they create unique entities.
    Also re-anchors the deterministic clock so each test starts at the
    same logical moment.
    """
    try:
        api_client._request("POST", "/__test__/reset", None, {})
    except Exception:
        pass
    try:
        anchor_clock()
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — shared constants canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def practice_admin_headers():
    return TEST_USERS["practice_admin_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Entity-backed FALLBACK headers — safe only for tests that do NOT
# exercise ownership. Ownership-gated calls MUST mint per-instance
# headers via make_therapist_headers / make_supervisor_headers.
# ---------------------------------------------------------------------------
@pytest.fixture
def therapist_fallback_headers():
    return TEST_USERS["therapist_fallback_headers"]


@pytest.fixture
def supervisor_fallback_headers():
    return TEST_USERS["supervisor_fallback_headers"]
