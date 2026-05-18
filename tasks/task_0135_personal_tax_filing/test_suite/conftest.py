"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- IRSAdjudicator is OPAQUE — shared *_headers constants are canonical.
- Taxpayer is ENTITY-BACKED. The fallback header in TEST_USERS is
  ONLY for tests that do not exercise ownership. Ownership-gated
  tests must mint headers via make_taxpayer_headers(taxpayer["id"])
  using the actual Taxpayer.id returned by POST /taxpayers.
"""
from __future__ import annotations

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle owned by the
    runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    """Best-effort wipe of the implementation's in-memory store
    between tests. Implementations that do not expose
    /__test__/reset are tolerated; tests still pass as long as they
    create unique entities.
    """
    try:
        api_client._request(
            "POST", "/__test__/reset", None,
            TEST_USERS["irs_adjudicator_headers"],
        )
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — shared constants canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def irs_adjudicator_headers():
    return TEST_USERS["irs_adjudicator_headers"]


@pytest.fixture
def irs_adjudicator_headers_alt():
    return TEST_USERS["irs_adjudicator_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed fallback header — ONLY safe when ownership is NOT
# exercised. Ownership-gated Taxpayer calls MUST mint per-instance
# headers via make_taxpayer_headers(taxpayer["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def taxpayer_fallback_headers():
    return TEST_USERS["taxpayer_fallback_headers"]
