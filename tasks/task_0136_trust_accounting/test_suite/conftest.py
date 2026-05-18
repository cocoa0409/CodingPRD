"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- Grantor / TaxPreparer / Auditor are OPAQUE (Grantor X-User-ID is
  recorded on the Trust at creation time and must match on later
  grantor-scoped calls; fixtures thread this).
- Trustee and Beneficiary are ENTITY-BACKED. The fallback constants
  in TEST_USERS are ONLY safe for tests that do not exercise
  ownership. Ownership-gated tests must mint headers via
  make_trustee_headers(trustee["user_id"]) or
  make_beneficiary_headers(beneficiary["id"]).
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
    """Best-effort wipe of the implementation's in-memory store
    between tests. Implementations that do not expose /__test__/reset
    are tolerated; tests still pass as long as they create unique
    entities.
    """
    try:
        api_client._request(
            "POST", "/__test__/reset", None,
            TEST_USERS["auditor_headers"],
        )
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — shared constants canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def grantor_headers():
    return TEST_USERS["grantor_headers"]


@pytest.fixture
def grantor_headers_alt():
    return TEST_USERS["grantor_headers_alt"]


@pytest.fixture
def tax_preparer_headers():
    return TEST_USERS["tax_preparer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Entity-backed fallback headers — ONLY safe when ownership is NOT
# exercised. Ownership-gated calls MUST mint per-instance headers via
# make_trustee_headers(trustee["user_id"]) or
# make_beneficiary_headers(beneficiary["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def trustee_fallback_headers():
    return TEST_USERS["trustee_fallback_headers"]


@pytest.fixture
def beneficiary_fallback_headers():
    return TEST_USERS["beneficiary_fallback_headers"]
