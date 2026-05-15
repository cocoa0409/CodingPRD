"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- VenueAdmin, VenueOps, ServiceProvider, GateOperator, TestHarness are
  OPAQUE — shared constants are canonical.
- Exhibitor is ENTITY-BACKED (X-User-ID == exhibitor_id stored on
  ExhibitorApplication and propagated to BoothAllocation, DockSlot,
  WorkOrder, SponsorEntitlement). Tests that exercise ownership MUST
  mint headers via make_exhibitor_headers(exhibitor_id).
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
def venue_admin_headers():
    return TEST_USERS["venue_admin_headers"]


@pytest.fixture
def venue_admin_headers_alt():
    return TEST_USERS["venue_admin_headers_alt"]


@pytest.fixture
def venue_ops_headers():
    return TEST_USERS["venue_ops_headers"]


@pytest.fixture
def service_provider_headers():
    return TEST_USERS["service_provider_headers"]


@pytest.fixture
def gate_operator_headers():
    return TEST_USERS["gate_operator_headers"]


@pytest.fixture
def test_harness_headers():
    return TEST_USERS["test_harness_headers"]


# ---------------------------------------------------------------------------
# Entity-backed Exhibitor fallback — only safe when ownership is NOT
# exercised. Ownership-gated calls MUST mint per-instance headers via
# make_exhibitor_headers(exhibitor_id).
# ---------------------------------------------------------------------------
@pytest.fixture
def exhibitor_fallback_headers():
    return TEST_USERS["exhibitor_headers"]
