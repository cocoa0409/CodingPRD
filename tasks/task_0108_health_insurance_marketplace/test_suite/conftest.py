"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- MarketplaceAdmin / CustomerService are OPAQUE — shared headers
  constants are canonical.
- Applicant is OPAQUE but X-User-ID is recorded as
  Application.applicant_id; ownership-gated tests must mint headers via
  make_applicant_headers(id) using the same id that was used when the
  Application was created.
- Insurer is ENTITY-BACKED — the fallback header in TEST_USERS is ONLY
  safe when ownership is NOT exercised; Plan-management tests must mint
  headers via make_insurer_headers(insurer["id"]).
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
def customer_service_headers():
    return TEST_USERS["customer_service_headers"]


# ---------------------------------------------------------------------------
# Applicant fallback — ONLY safe when no Application ownership is
# exercised; ownership-gated tests mint per-instance headers via
# make_applicant_headers(applicant_id).
# ---------------------------------------------------------------------------
@pytest.fixture
def applicant_fallback_headers():
    return TEST_USERS["applicant_fallback_headers"]


@pytest.fixture
def applicant_fallback_headers_alt():
    return TEST_USERS["applicant_fallback_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed Insurer fallback — ONLY safe when ownership is NOT
# exercised. Plan-management tests must mint per-instance headers via
# make_insurer_headers(insurer["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def insurer_fallback_headers():
    return TEST_USERS["insurer_fallback_headers"]
