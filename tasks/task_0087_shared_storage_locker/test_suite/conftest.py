"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- Operator and InsuranceAgent are OPAQUE — shared constants canonical.
- Renter is OPAQUE-but-ownership-binding (X-User-ID must equal
  Rental.renter_id). Tests that exercise ownership-gated calls MUST
  use make_renter_headers(rental['renter_id']).
- RepairTechnician is OPAQUE-but-assignment-binding (X-User-ID must
  equal RepairTicket.assigned_technician_id on /repair). The
  /repair endpoint MUST use make_technician_headers(...).
"""
from __future__ import annotations

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client, reset_clock_to_epoch


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    """Wipe the implementation's in-memory store before each test so
    catalog state cannot leak. The /__test__/reset endpoint is a
    test-infrastructure extension parallel to the test-driver
    endpoints in PRD §2.11; a 404 from an implementation that does
    not expose it is tolerated."""
    try:
        api_client._request("POST", "/__test__/reset", None, {})
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Operator headers (opaque — shared constants canonical, PRD §2.1)
# ---------------------------------------------------------------------------
@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def operator_headers_alt():
    return TEST_USERS["operator_headers_alt"]


# ---------------------------------------------------------------------------
# InsuranceAgent headers (opaque — shared constants canonical, PRD §2.1)
# ---------------------------------------------------------------------------
@pytest.fixture
def insurance_agent_headers():
    return TEST_USERS["insurance_agent_headers"]


@pytest.fixture
def insurance_agent_headers_alt():
    return TEST_USERS["insurance_agent_headers_alt"]


# ---------------------------------------------------------------------------
# Renter / Technician fallback headers (ownership-irrelevant tests only)
# ---------------------------------------------------------------------------
@pytest.fixture
def renter_fallback_headers():
    """For tests that do NOT exercise Rental ownership. For
    ownership-gated calls use make_renter_headers(rental['renter_id'])."""
    return TEST_USERS["renter_headers"]


@pytest.fixture
def renter_fallback_headers_alt():
    return TEST_USERS["renter_headers_alt"]


@pytest.fixture
def technician_fallback_headers():
    """For tests that do NOT exercise the assigned-technician check on
    POST /repair-tickets/{id}/repair. Otherwise use
    make_technician_headers(ticket['assigned_technician_id'])."""
    return TEST_USERS["technician_headers"]


@pytest.fixture(autouse=True)
def _reset_logical_clock():
    """PRD §2.11: tests that don't touch the sweep should observe a
    fresh logical clock. We anchor at TEST_EPOCH on every test;
    failures here are tolerated so tests that don't need it still
    pass when the implementation lacks the test-driver endpoint."""
    try:
        reset_clock_to_epoch()
    except Exception:
        pass
    yield
