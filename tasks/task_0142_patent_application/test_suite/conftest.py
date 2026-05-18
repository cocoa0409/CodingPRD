"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires the session-scoped API client and per-role header fixtures.

PRD §2.1 identity rules:
- Examiner and USPTOAdmin are OPAQUE — the shared TEST_USERS constants
  are canonical.
- Applicant is ENTITY-BACKED (X-User-ID == Applicant.id) — tests that
  exercise ownership MUST mint headers via
  make_applicant_headers(applicant["id"]) and NEVER fall back to
  applicant_fallback_headers.
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
def uspto_admin_headers():
    return TEST_USERS["uspto_admin_headers"]


@pytest.fixture
def uspto_admin_headers_alt():
    return TEST_USERS["uspto_admin_headers_alt"]


@pytest.fixture
def examiner_headers():
    return TEST_USERS["examiner_headers"]


@pytest.fixture
def examiner_headers_alt():
    return TEST_USERS["examiner_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed fallback — ONLY for tests that do not exercise
# ownership (PRD §2.1). Ownership-gated calls must mint per-instance
# headers via make_applicant_headers(applicant["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def applicant_fallback_headers():
    return TEST_USERS["applicant_headers"]
