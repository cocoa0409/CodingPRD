"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- PlatformAdmin / DisputeOps are OPAQUE — shared *_headers constants
  are canonical.
- Rider and Driver are ENTITY-BACKED. The fallback headers in
  TEST_USERS are ONLY for tests that do not exercise ownership.
  Ownership-gated tests must mint headers via make_rider_headers(
  rider["id"]) / make_driver_headers(driver["id"]) using the actual
  entity id returned by POST /riders or POST /drivers.
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
            TEST_USERS["platform_admin_headers"],
        )
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — shared constants are canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def admin_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


@pytest.fixture
def dispute_ops_headers():
    return TEST_USERS["dispute_ops_headers"]


@pytest.fixture
def dispute_ops_headers_alt():
    return TEST_USERS["dispute_ops_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed fallback headers — ONLY safe when ownership is NOT
# exercised. Ownership-gated calls MUST mint per-instance headers via
# make_rider_headers(rider["id"]) / make_driver_headers(driver["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def rider_fallback_headers():
    return TEST_USERS["rider_fallback_headers"]


@pytest.fixture
def driver_fallback_headers():
    return TEST_USERS["driver_fallback_headers"]
