"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role fallback headers and the session-scoped API client.

PRD §2.1 identity rules:
- All three roles (OrderingProvider, LabTech, LabDirector) are
  ENTITY-BACKED by the Clinician table. Tests that require
  ownership-gated behavior mint headers via the make_*_headers
  builders with the actual Clinician.id, NEVER the shared fallback
  constants exposed here. The fallback fixtures below are safe ONLY
  for tests that do NOT exercise ownership (auth header tests, role
  permission tests, NotFound tests, malformed-payload tests,
  pagination tests).
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
    """Best-effort reset of the implementation's in-memory store between
    tests. Implementations that do not expose /__test__/reset are
    tolerated; tests still pass as long as they create their own unique
    entities and never share mutable state across tests.
    """
    try:
        api_client._request("POST", "/__test__/reset", None, {})
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Entity-backed FALLBACK headers — safe only for auth/role-mismatch and
# NotFound / malformed-payload / pagination tests. Ownership-gated calls
# MUST mint per-instance headers via make_<role>_headers(clinician_id).
# ---------------------------------------------------------------------------
@pytest.fixture
def ordering_provider_fallback_headers():
    return TEST_USERS["ordering_provider_fallback_headers"]


@pytest.fixture
def lab_tech_fallback_headers():
    return TEST_USERS["lab_tech_fallback_headers"]


@pytest.fixture
def lab_director_fallback_headers():
    return TEST_USERS["lab_director_fallback_headers"]
