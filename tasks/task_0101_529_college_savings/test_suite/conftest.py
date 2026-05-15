"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- PlanAdministrator is OPAQUE — admin_headers shared constant canonical.
- Donor is ENTITY-BACKED. The donor_headers fallback in TEST_USERS is
  ONLY for tests that do not exercise ownership. Ownership-gated tests
  must mint headers via make_donor_headers(donor["id"]).
- Beneficiary is ENTITY-BACKED. Same fallback rule as Donor.
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


# ---------------------------------------------------------------------------
# Entity-backed fallback headers — ONLY safe when ownership is NOT
# exercised (header-missing tests, role-mismatch tests, NotFound paths).
# Ownership-gated calls MUST mint per-instance headers via
# make_donor_headers / make_beneficiary_headers.
# ---------------------------------------------------------------------------
@pytest.fixture
def donor_fallback_headers():
    return TEST_USERS["donor_headers"]


@pytest.fixture
def beneficiary_fallback_headers():
    return TEST_USERS["beneficiary_headers"]
