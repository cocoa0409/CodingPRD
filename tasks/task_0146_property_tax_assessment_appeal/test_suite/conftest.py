"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- Assessor / Treasurer are OPAQUE — shared *_headers constants are
  canonical.
- Owner / HearingOfficer are ENTITY-BACKED. The fallback headers in
  TEST_USERS are ONLY for tests that do not exercise ownership.
  Ownership-gated tests must mint headers via make_owner_headers
  (owner["id"]) / make_hearing_officer_headers(officer["id"]) using
  the actual entity ids returned by the create endpoints.
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
        api_client._request(
            "POST", "/__test__/reset", None,
            TEST_USERS["assessor_headers"],
        )
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — shared constants canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def assessor_headers():
    return TEST_USERS["assessor_headers"]


@pytest.fixture
def assessor_headers_alt():
    return TEST_USERS["assessor_headers_alt"]


@pytest.fixture
def treasurer_headers():
    return TEST_USERS["treasurer_headers"]


@pytest.fixture
def treasurer_headers_alt():
    return TEST_USERS["treasurer_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed fallback headers — ONLY safe when ownership is NOT
# exercised. Ownership-gated calls MUST mint per-instance headers via
# make_owner_headers(owner["id"]) / make_hearing_officer_headers(officer["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def owner_fallback_headers():
    return TEST_USERS["owner_fallback_headers"]


@pytest.fixture
def hearing_officer_fallback_headers():
    return TEST_USERS["hearing_officer_fallback_headers"]
