"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- PlatformOperator is OPAQUE — shared *_headers constants are
  canonical.
- ComplianceOfficer, Borrower, Investor are ENTITY-BACKED. The fallback
  headers in TEST_USERS are ONLY for tests that do not exercise
  ownership / segregation. Ownership-gated tests must mint headers via
  make_<role>_headers(<entity>["id"]) using the actual entity ids
  returned by the create endpoints.
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
            TEST_USERS["platform_operator_headers"],
        )
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — shared constants canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def platform_operator_headers():
    return TEST_USERS["platform_operator_headers"]


@pytest.fixture
def platform_operator_headers_alt():
    return TEST_USERS["platform_operator_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed fallback headers — ONLY safe when ownership is NOT
# exercised. Ownership-gated calls MUST mint per-instance headers via
# make_borrower_headers / make_investor_headers /
# make_compliance_officer_headers using actual entity ids.
# ---------------------------------------------------------------------------
@pytest.fixture
def borrower_fallback_headers():
    return TEST_USERS["borrower_fallback_headers"]


@pytest.fixture
def investor_fallback_headers():
    return TEST_USERS["investor_fallback_headers"]


@pytest.fixture
def compliance_officer_fallback_headers():
    return TEST_USERS["compliance_officer_fallback_headers"]
