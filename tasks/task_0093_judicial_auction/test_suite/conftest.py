"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- CourtClerk, AuctionAdmin, Observer are OPAQUE — shared constants
  canonical.
- Bidder is ENTITY-BACKED (X-User-ID is the acting BidderAccount.id).
  Tests that exercise ownership MUST mint headers via
  make_bidder_headers(account["id"]).
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
def court_clerk_headers():
    return TEST_USERS["court_clerk_headers"]


@pytest.fixture
def court_clerk_headers_alt():
    return TEST_USERS["court_clerk_headers_alt"]


@pytest.fixture
def auction_admin_headers():
    return TEST_USERS["auction_admin_headers"]


@pytest.fixture
def auction_admin_headers_alt():
    return TEST_USERS["auction_admin_headers_alt"]


@pytest.fixture
def observer_headers():
    return TEST_USERS["observer_headers"]


# ---------------------------------------------------------------------------
# Entity-backed fallback — only for tests that DO NOT exercise ownership.
# Ownership-gated calls MUST mint per-instance headers via
# make_bidder_headers(account["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def bidder_fallback_headers():
    return TEST_USERS["bidder_headers"]
