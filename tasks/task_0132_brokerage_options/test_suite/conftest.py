"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- ComplianceOfficer / PlatformAdmin are OPAQUE — shared *_headers
  constants are canonical.
- Customer is ENTITY-BACKED. The fallback header in TEST_USERS is ONLY
  for tests that do not exercise ownership (header-missing, role-
  mismatch, 404-on-non-existent, or ERR_OWNERSHIP_VIOLATION negative
  paths). Ownership-gated tests must mint headers via
  make_customer_headers(customer["id"]) using the actual entity ids
  returned by the create endpoints.
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
# Opaque-role headers — shared constants canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def compliance_headers_alt():
    return TEST_USERS["compliance_headers_alt"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Entity-backed Customer fallback headers — ONLY safe when ownership is
# NOT exercised. Ownership-gated calls MUST mint per-instance headers
# via make_customer_headers(customer["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def customer_fallback_headers():
    return TEST_USERS["customer_fallback_headers"]


@pytest.fixture
def customer_other_headers():
    """A second customer-role header backed by a different (also fake)
    X-User-ID. Used to assert ERR_OWNERSHIP_VIOLATION on cross-customer
    access attempts."""
    return TEST_USERS["customer_other_headers"]
