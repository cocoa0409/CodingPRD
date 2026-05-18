"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- ComplianceOfficer / TaxAdmin / system are OPAQUE — shared
  *_headers constants are canonical.
- ClientUser is ENTITY-BACKED. The fallback header in TEST_USERS is
  ONLY for tests that do not exercise ownership. Ownership-gated
  tests must mint headers via make_client_user_headers(client["id"])
  using the actual Client.id returned by POST /clients.
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
            TEST_USERS["compliance_officer_headers"],
        )
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — shared constants canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_headers_alt():
    return TEST_USERS["compliance_officer_headers_alt"]


@pytest.fixture
def tax_admin_headers():
    return TEST_USERS["tax_admin_headers"]


@pytest.fixture
def system_headers():
    return TEST_USERS["system_headers"]


@pytest.fixture
def advisor_headers():
    return TEST_USERS["advisor_headers"]


# ---------------------------------------------------------------------------
# Entity-backed fallback header — ONLY safe when ownership is NOT
# exercised. Ownership-gated ClientUser calls MUST mint per-instance
# headers via make_client_user_headers(client["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def client_user_fallback_headers():
    return TEST_USERS["client_user_fallback_headers"]
