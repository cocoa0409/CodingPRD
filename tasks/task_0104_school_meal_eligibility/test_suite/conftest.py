"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- Parent is ENTITY-BACKED. The parent_headers fallback in TEST_USERS is
  ONLY for tests that do not exercise ownership. Ownership-gated tests
  must mint headers via make_parent_headers(parent_account["id"]).
- DistrictReviewer, CafeteriaManager, AuditOfficer are OPAQUE — shared
  TEST_USERS constants are canonical.
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
# Opaque-role headers — shared constants canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def reviewer_headers_alt():
    return TEST_USERS["reviewer_headers_alt"]


@pytest.fixture
def cafeteria_headers():
    return TEST_USERS["cafeteria_headers"]


@pytest.fixture
def cafeteria_headers_alt():
    return TEST_USERS["cafeteria_headers_alt"]


@pytest.fixture
def audit_headers():
    return TEST_USERS["audit_headers"]


@pytest.fixture
def audit_headers_alt():
    return TEST_USERS["audit_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed fallback headers — ONLY safe when ownership is NOT
# exercised (header-missing tests, role-mismatch tests, NotFound paths).
# Ownership-gated calls MUST mint per-instance headers via
# make_parent_headers.
# ---------------------------------------------------------------------------
@pytest.fixture
def parent_fallback_headers():
    return TEST_USERS["parent_headers"]
