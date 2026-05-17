"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- IntakeCoordinator, BillingSpecialist, PlatformAdmin are OPAQUE —
  shared role-header constants are canonical.
- FieldClinician is ENTITY-BACKED:Clinician. The fallback header in
  TEST_USERS is ONLY for tests that do not exercise ownership.
  Ownership-gated tests must mint headers via
  make_field_clinician_headers(clinician["id"]).
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
def intake_coordinator_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def intake_coordinator_headers_alt():
    return TEST_USERS["intake_coordinator_headers_alt"]


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]


@pytest.fixture
def billing_specialist_headers_alt():
    return TEST_USERS["billing_specialist_headers_alt"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def platform_admin_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed fallback header — ONLY safe when ownership is NOT
# exercised. Ownership-gated calls MUST mint per-instance headers via
# make_field_clinician_headers(clinician["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def field_clinician_fallback_headers():
    return TEST_USERS["field_clinician_fallback_headers"]
