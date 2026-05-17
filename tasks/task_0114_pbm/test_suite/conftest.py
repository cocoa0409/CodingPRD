"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rule: every PBM role (PBMAdmin, Prescriber,
ClinicalReviewer, ClaimsAdjudicator) is OPAQUE — shared role-header
constants are canonical for every call.
"""
from __future__ import annotations

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle owned by the
    runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    """Best-effort wipe of the implementation's in-memory store between
    tests. Implementations that do not expose /__test__/reset are
    tolerated; tests still pass as long as they create unique
    entities."""
    try:
        api_client._request("POST", "/__test__/reset", None, {})
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — PRD §2.1.
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_headers_alt():
    return TEST_USERS["admin_headers_alt"]


@pytest.fixture
def prescriber_headers():
    return TEST_USERS["prescriber_headers"]


@pytest.fixture
def prescriber_headers_alt():
    return TEST_USERS["prescriber_headers_alt"]


@pytest.fixture
def clinical_reviewer_headers():
    return TEST_USERS["clinical_reviewer_headers"]


@pytest.fixture
def clinical_reviewer_headers_alt():
    return TEST_USERS["clinical_reviewer_headers_alt"]


@pytest.fixture
def claims_adjudicator_headers():
    return TEST_USERS["claims_adjudicator_headers"]


@pytest.fixture
def claims_adjudicator_headers_alt():
    return TEST_USERS["claims_adjudicator_headers_alt"]
