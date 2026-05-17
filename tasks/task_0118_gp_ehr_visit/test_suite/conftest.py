"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- Provider and PatientPortalUser are ENTITY-BACKED. Tests that require
  ownership-gated behavior mint headers via make_provider_headers(...)
  or make_patient_portal_headers(...) — never the shared fallback
  constants.
- Nurse, Receptionist, BillingClerk, Pharmacist, ClinicAdmin,
  TestHarness are OPAQUE — shared TEST_USERS headers are canonical.
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
def receptionist_headers():
    return TEST_USERS["receptionist_headers"]


@pytest.fixture
def nurse_headers():
    return TEST_USERS["nurse_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def pharmacist_headers():
    return TEST_USERS["pharmacist_headers"]


@pytest.fixture
def pharmacist_headers_alt():
    return TEST_USERS["pharmacist_headers_alt"]


@pytest.fixture
def clinic_admin_headers():
    return TEST_USERS["clinic_admin_headers"]


@pytest.fixture
def test_harness_headers():
    return TEST_USERS["test_harness_headers"]


# ---------------------------------------------------------------------------
# Entity-backed FALLBACK headers — safe only for tests that do NOT
# exercise ownership. Ownership-gated calls MUST mint per-instance
# headers via make_provider_headers / make_patient_portal_headers.
# ---------------------------------------------------------------------------
@pytest.fixture
def provider_fallback_headers():
    return TEST_USERS["provider_fallback_headers"]


@pytest.fixture
def patient_portal_fallback_headers():
    return TEST_USERS["patient_portal_fallback_headers"]
