"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires the session-scoped API client and per-role header fixtures.

PRD §2.1 identity rules:
- SystemOperator is OPAQUE — the shared TEST_USERS constants are
  canonical.
- DistrictAdmin (X-User-ID == District.id) and FamilyUser (X-User-ID
  == Family.id) are ENTITY-BACKED — tests that exercise ownership
  MUST mint headers via make_district_admin_headers(district["id"])
  / make_family_user_headers(family["id"]) and NEVER fall back to
  district_admin_fallback_headers / family_user_fallback_headers.
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
# Opaque-role headers — shared constant canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def system_operator_headers():
    return TEST_USERS["system_operator_headers"]


@pytest.fixture
def system_operator_headers_alt():
    return TEST_USERS["system_operator_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed fallbacks — ONLY for tests that do not exercise
# ownership (PRD §2.1). Ownership-gated calls must mint per-instance
# headers via make_district_admin_headers / make_family_user_headers.
# ---------------------------------------------------------------------------
@pytest.fixture
def district_admin_fallback_headers():
    return TEST_USERS["district_admin_headers"]


@pytest.fixture
def family_user_fallback_headers():
    return TEST_USERS["family_user_headers"]
