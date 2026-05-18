"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- PlatformAdmin is OPAQUE — shared admin_headers constants are
  canonical.
- Cardholder is ENTITY-BACKED. The fallback header in TEST_USERS is
  ONLY for tests that do not exercise ownership (header-missing,
  role-mismatch, 404 on bogus path). Ownership-gated tests must mint
  headers via make_cardholder_headers(cardholder["id"]) using the
  actual entity ids returned by the create endpoints.
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
            TEST_USERS["admin_headers"],
        )
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role header — shared constant is canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_headers_alt():
    return TEST_USERS["admin_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed fallback header — ONLY safe when ownership is NOT
# exercised. Ownership-gated calls MUST mint per-instance headers via
# make_cardholder_headers(cardholder["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def cardholder_fallback_headers():
    return TEST_USERS["cardholder_fallback_headers"]
