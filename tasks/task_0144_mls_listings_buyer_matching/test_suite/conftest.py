"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- MlsAdmin is OPAQUE — shared TEST_USERS["mls_admin_headers"] is canonical.
- ListingAgent and BuyerAgent are ENTITY-BACKED. The fallback fixtures
  here are SAFE only for tests that do not exercise ownership.
  Ownership-gated tests must mint headers via
  make_listing_agent_headers(agent_id) / make_buyer_agent_headers(agent_id)
  using the actual entity ids returned by POST /agents.
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
            TEST_USERS["mls_admin_headers"],
        )
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — shared constants canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def mls_admin_headers():
    return TEST_USERS["mls_admin_headers"]


@pytest.fixture
def mls_admin_headers_alt():
    return TEST_USERS["mls_admin_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed fallback headers — ONLY safe when ownership is NOT
# exercised. Ownership-gated calls MUST mint per-instance headers via
# make_listing_agent_headers / make_buyer_agent_headers.
# ---------------------------------------------------------------------------
@pytest.fixture
def listing_agent_fallback_headers():
    return TEST_USERS["listing_agent_fallback_headers"]


@pytest.fixture
def buyer_agent_fallback_headers():
    return TEST_USERS["buyer_agent_fallback_headers"]
