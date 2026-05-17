"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- Servicer / LossMitigationUnderwriter / PmiUnderwriter /
  ForeclosureAttorney / PlatformAdmin are OPAQUE — shared *_headers
  constants are canonical.
- Borrower is ENTITY-BACKED. The fallback header in TEST_USERS is
  ONLY for tests that do not exercise ownership. Ownership-gated
  tests must mint headers via make_borrower_headers(borrower["id"])
  using the actual entity ids returned by the create endpoints.
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
        api_client._request(
            "POST", "/__test__/reset", None,
            TEST_USERS["platform_admin_headers"],
        )
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — shared constants canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def servicer_headers():
    return TEST_USERS["servicer_headers"]


@pytest.fixture
def servicer_headers_alt():
    return TEST_USERS["servicer_headers_alt"]


@pytest.fixture
def lmu_headers():
    return TEST_USERS["lmu_headers"]


@pytest.fixture
def lmu_headers_alt():
    return TEST_USERS["lmu_headers_alt"]


@pytest.fixture
def pmi_underwriter_headers():
    return TEST_USERS["pmi_underwriter_headers"]


@pytest.fixture
def pmi_underwriter_headers_alt():
    return TEST_USERS["pmi_underwriter_headers_alt"]


@pytest.fixture
def foreclosure_attorney_headers():
    return TEST_USERS["foreclosure_attorney_headers"]


@pytest.fixture
def foreclosure_attorney_headers_alt():
    return TEST_USERS["foreclosure_attorney_headers_alt"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Entity-backed fallback header — ONLY safe when ownership is NOT
# exercised. Ownership-gated calls MUST mint per-instance headers via
# make_borrower_headers(borrower["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def borrower_fallback_headers():
    return TEST_USERS["borrower_fallback_headers"]
