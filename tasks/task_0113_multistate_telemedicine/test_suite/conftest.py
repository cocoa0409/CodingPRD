"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- PlatformAdmin, ComplianceOfficer, Payer are OPAQUE — shared role-
  header constants are canonical.
- Physician is ENTITY-BACKED. The fallback header in TEST_USERS is ONLY
  for tests that do not exercise ownership. Ownership-gated tests must
  mint headers via make_physician_headers(physician["id"]).
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
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_headers_alt():
    return TEST_USERS["admin_headers_alt"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_headers_alt():
    return TEST_USERS["compliance_officer_headers_alt"]


@pytest.fixture
def payer_headers():
    return TEST_USERS["payer_headers"]


@pytest.fixture
def payer_headers_alt():
    return TEST_USERS["payer_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed fallback header — ONLY safe when ownership is NOT
# exercised. Ownership-gated calls MUST mint per-instance headers via
# make_physician_headers(physician["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def physician_fallback_headers():
    return TEST_USERS["physician_fallback_headers"]
