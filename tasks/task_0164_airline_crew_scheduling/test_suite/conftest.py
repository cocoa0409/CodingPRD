"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- CrewScheduler / UnionSteward are OPAQUE — shared *_headers constants
  are canonical.
- Pilot / FlightAttendant are ENTITY-BACKED. The fallback headers in
  TEST_USERS are ONLY for tests that do not exercise ownership.
  Ownership-gated tests must mint headers via
  make_pilot_headers(crew_member["id"]).
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
    Also resets the in-process seniority sequence so generated
    union_seniority_number values don't collide with the wiped server
    state.
    """
    try:
        api_client._request(
            "POST", "/__test__/reset", None,
            TEST_USERS["crew_scheduler_headers"],
        )
    except Exception:
        pass
    # Reset per-rank seniority counter used by create_crew_member_payload.
    try:
        from test_helpers import factories as _f
        _f._seniority_seq.clear()
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — shared constants are canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def scheduler_headers():
    return TEST_USERS["crew_scheduler_headers"]


@pytest.fixture
def scheduler_headers_alt():
    return TEST_USERS["crew_scheduler_headers_alt"]


@pytest.fixture
def steward_headers():
    return TEST_USERS["union_steward_headers"]


@pytest.fixture
def steward_headers_alt():
    return TEST_USERS["union_steward_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed Pilot / FA fallback headers — ONLY safe when ownership is
# NOT exercised. Ownership-gated calls MUST mint per-instance headers via
# make_pilot_headers(crew_member["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def pilot_fallback_headers():
    return TEST_USERS["pilot_fallback_headers"]


@pytest.fixture
def fa_fallback_headers():
    return TEST_USERS["flight_attendant_fallback_headers"]
