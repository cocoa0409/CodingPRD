"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- MedicalDirector, Consultant, AttendingPhysician, SeniorPhysician,
  Nurse, FinanceOfficer are OPAQUE — shared constants canonical.
- Customer is ENTITY-BACKED (X-User-ID == Customer.id). Tests that
  exercise ownership MUST mint headers via
  make_customer_headers(customer["id"]).
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
def medical_director_headers():
    return TEST_USERS["medical_director_headers"]


@pytest.fixture
def medical_director_headers_alt():
    return TEST_USERS["medical_director_headers_alt"]


@pytest.fixture
def consultant_headers():
    return TEST_USERS["consultant_headers"]


@pytest.fixture
def consultant_headers_alt():
    return TEST_USERS["consultant_headers_alt"]


@pytest.fixture
def attending_physician_headers():
    return TEST_USERS["attending_physician_headers"]


@pytest.fixture
def attending_physician_headers_alt():
    return TEST_USERS["attending_physician_headers_alt"]


@pytest.fixture
def senior_physician_headers():
    return TEST_USERS["senior_physician_headers"]


@pytest.fixture
def senior_physician_headers_alt():
    return TEST_USERS["senior_physician_headers_alt"]


@pytest.fixture
def nurse_headers():
    return TEST_USERS["nurse_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


# ---------------------------------------------------------------------------
# Entity-backed Customer fallback — only safe when ownership is NOT
# exercised. Ownership-gated calls MUST mint per-instance headers via
# make_customer_headers(customer["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def customer_fallback_headers():
    return TEST_USERS["customer_headers"]
