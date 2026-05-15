"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- CDCSupervisor, RiskExpert, PressOfficer, SupplyManager are OPAQUE —
  shared constants canonical.
- HospitalReporter, LabTechnician, CDCDispatcher, CDCTracer are
  ENTITY-BACKED (X-User-ID is the acting ReportingInstitution.id).
  Tests that exercise ownership-gated calls MUST use
  make_<role>_headers(institution["id"]).
"""
from __future__ import annotations

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    """Wipe the implementation's in-memory store before each test so
    catalog state cannot leak across tests. The /__test__/reset
    endpoint is a test-infrastructure extension parallel to the
    test-driver endpoints in PRD §2.9; a 404 from an implementation
    that does not expose it is tolerated."""
    try:
        api_client._request("POST", "/__test__/reset", None, {})
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — shared constants canonical (PRD §2.1)
# ---------------------------------------------------------------------------
@pytest.fixture
def supervisor_headers():
    return TEST_USERS["cdc_supervisor_headers"]


@pytest.fixture
def supervisor_headers_alt():
    return TEST_USERS["cdc_supervisor_headers_alt"]


@pytest.fixture
def risk_expert_headers():
    return TEST_USERS["risk_expert_headers"]


@pytest.fixture
def press_officer_headers():
    return TEST_USERS["press_officer_headers"]


@pytest.fixture
def supply_manager_headers():
    return TEST_USERS["supply_manager_headers"]


# ---------------------------------------------------------------------------
# Entity-backed fallback headers — for tests that DO NOT exercise
# ownership (header-missing, role-mismatch, NotFound paths).
# Ownership-gated calls MUST mint per-instance headers via
# make_<role>_headers(institution["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def hospital_reporter_fallback_headers():
    return TEST_USERS["hospital_reporter_headers"]


@pytest.fixture
def lab_technician_fallback_headers():
    return TEST_USERS["lab_technician_headers"]


@pytest.fixture
def cdc_dispatcher_fallback_headers():
    return TEST_USERS["cdc_dispatcher_headers"]


@pytest.fixture
def cdc_tracer_fallback_headers():
    return TEST_USERS["cdc_tracer_headers"]
