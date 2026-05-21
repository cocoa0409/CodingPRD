"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- ProgramAdmin / BookingAgent are OPAQUE — shared *_headers constants
  are canonical.
- Member is ENTITY-BACKED. The fallback headers in TEST_USERS are ONLY
  for tests that do not exercise ownership. Ownership-gated tests must
  mint headers via make_member_headers(member["id"]) using the actual
  Member.id returned by POST /members.
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
            TEST_USERS["program_admin_headers"],
        )
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — shared constants are canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def admin_headers_alt():
    return TEST_USERS["program_admin_headers_alt"]


@pytest.fixture
def booking_agent_headers():
    return TEST_USERS["booking_agent_headers"]


@pytest.fixture
def booking_agent_headers_alt():
    return TEST_USERS["booking_agent_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed Member fallback headers — ONLY safe when ownership is NOT
# exercised. Ownership-gated calls MUST mint per-instance headers via
# make_member_headers(member["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def member_fallback_headers():
    return TEST_USERS["member_fallback_headers"]
