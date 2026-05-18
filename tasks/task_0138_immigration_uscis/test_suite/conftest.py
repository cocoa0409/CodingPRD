"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- Officer / Supervisor are OPAQUE — shared *_headers constants are
  canonical.
- Petitioner / Beneficiary are ENTITY-BACKED. The fallback header in
  TEST_USERS is ONLY for tests that do not exercise ownership
  (header-missing, role-mismatch, 404 paths). Ownership-gated tests
  must mint headers via make_petitioner_headers(petitioner["id"])
  using the actual Petitioner.id returned by POST /petitioners.
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
            TEST_USERS["supervisor_headers"],
        )
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — shared constants canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def officer_headers_alt():
    return TEST_USERS["officer_headers_alt"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def supervisor_headers_alt():
    return TEST_USERS["supervisor_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed fallback headers — ONLY safe when ownership is NOT
# exercised. Ownership-gated Petitioner/Beneficiary calls MUST mint
# per-instance headers via make_petitioner_headers / make_beneficiary_headers
# using the actual entity id.
# ---------------------------------------------------------------------------
@pytest.fixture
def petitioner_fallback_headers():
    return TEST_USERS["petitioner_fallback_headers"]


@pytest.fixture
def beneficiary_fallback_headers():
    return TEST_USERS["beneficiary_fallback_headers"]
