"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- BrokerOps, DeclarationOfficer, DocReviewer, FilingOfficer,
  InspectionOfficer, SettlementOfficer, SystemAdmin are OPAQUE —
  the shared constants are canonical.
- ClientUser is ENTITY-BACKED — X-User-ID must equal ClientCompany.id.
  Tests that exercise ClientUser ownership MUST use
  make_client_user_headers(client["id"]).
"""
from __future__ import annotations

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client, reset_clock_to_epoch


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_state_and_clock_between_tests():
    """Wipe the implementation's in-memory store AND anchor the logical
    clock at TEST_EPOCH before each test so state cannot leak between
    tests.

    /__test__/reset is a test-infrastructure extension parallel to PRD
    §2.12 admin-only test-driver endpoints; a 404 from an implementation
    that does not expose it is tolerated.

    The clock must be advanced AFTER the store reset (which puts the
    clock back at the implementation's initial epoch) so that fixture
    setups that create agreements with valid_from = TEST_EPOCH observe
    a clock inside the validity window.
    """
    try:
        api_client._request("POST", "/__test__/reset", None, {})
    except Exception:
        pass
    try:
        reset_clock_to_epoch()
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# BrokerOps (opaque — shared canonical, PRD §2.1)
# ---------------------------------------------------------------------------
@pytest.fixture
def broker_ops_headers():
    return TEST_USERS["broker_ops_headers"]


@pytest.fixture
def broker_ops_headers_alt():
    return TEST_USERS["broker_ops_headers_alt"]


# ---------------------------------------------------------------------------
# DeclarationOfficer (opaque)
# ---------------------------------------------------------------------------
@pytest.fixture
def declaration_officer_headers():
    return TEST_USERS["declaration_officer_headers"]


@pytest.fixture
def declaration_officer_headers_alt():
    return TEST_USERS["declaration_officer_headers_alt"]


# ---------------------------------------------------------------------------
# DocReviewer (opaque — PRD §2.9 SoD pairs this against FilingOfficer)
# ---------------------------------------------------------------------------
@pytest.fixture
def doc_reviewer_headers():
    return TEST_USERS["doc_reviewer_headers"]


@pytest.fixture
def doc_reviewer_headers_alt():
    return TEST_USERS["doc_reviewer_headers_alt"]


# ---------------------------------------------------------------------------
# FilingOfficer (opaque — PRD §2.9 SoD anchor)
# ---------------------------------------------------------------------------
@pytest.fixture
def filing_officer_headers():
    return TEST_USERS["filing_officer_headers"]


@pytest.fixture
def filing_officer_headers_alt():
    return TEST_USERS["filing_officer_headers_alt"]


# ---------------------------------------------------------------------------
# InspectionOfficer (opaque)
# ---------------------------------------------------------------------------
@pytest.fixture
def inspection_officer_headers():
    return TEST_USERS["inspection_officer_headers"]


@pytest.fixture
def inspection_officer_headers_alt():
    return TEST_USERS["inspection_officer_headers_alt"]


# ---------------------------------------------------------------------------
# SettlementOfficer (opaque)
# ---------------------------------------------------------------------------
@pytest.fixture
def settlement_officer_headers():
    return TEST_USERS["settlement_officer_headers"]


@pytest.fixture
def settlement_officer_headers_alt():
    return TEST_USERS["settlement_officer_headers_alt"]


# ---------------------------------------------------------------------------
# SystemAdmin (opaque) — drives _events/emit and _clock/advance
# ---------------------------------------------------------------------------
@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


# ---------------------------------------------------------------------------
# ClientUser fallback (NOT for ownership-gated calls — use make_client_user_headers)
# ---------------------------------------------------------------------------
@pytest.fixture
def client_user_fallback_headers():
    """Fallback ClientUser headers — for tests that do NOT exercise
    ClientCompany ownership (missing-auth, wrong-role, missing-resource).
    Ownership-gated tests MUST use make_client_user_headers(client_id)."""
    return TEST_USERS["client_user_headers"]
