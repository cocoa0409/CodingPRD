"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- Applicant is ENTITY-BACKED. Tests that exercise ownership MUST mint
  headers via make_applicant_headers(applicant_id) using the real
  Applicant.id, not the shared APPLICANT_FALLBACK_ID constant.
- Recommender is OPAQUE-BUT-EMAIL-MATCHED. Tests that exercise the
  recommender identity check MUST mint headers via
  make_recommender_headers(recommender_email).
- PlatformAdmin, AdmissionsOfficer, FinancialAidOfficer are OPAQUE —
  shared TEST_USERS constants are canonical.
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
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def platform_admin_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


@pytest.fixture
def admissions_officer_headers():
    return TEST_USERS["admissions_officer_headers"]


@pytest.fixture
def admissions_officer_headers_alt():
    return TEST_USERS["admissions_officer_headers_alt"]


@pytest.fixture
def financial_aid_officer_headers():
    return TEST_USERS["financial_aid_officer_headers"]


# ---------------------------------------------------------------------------
# Entity-backed fallback — ONLY for tests that do NOT exercise ownership
# (PRD §2.1). Ownership-gated Applicant calls MUST mint per-instance
# headers via make_applicant_headers.
# ---------------------------------------------------------------------------
@pytest.fixture
def applicant_headers_fallback():
    return TEST_USERS["applicant_headers_fallback"]


@pytest.fixture
def recommender_headers_fallback():
    return TEST_USERS["recommender_headers_fallback"]
