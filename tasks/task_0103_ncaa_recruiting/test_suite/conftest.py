"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- ComplianceOfficer / Coach / Booster / Auditor are OPAQUE — shared
  constants in TEST_USERS are canonical.
- Athlete is ENTITY-BACKED. The athlete_headers fallback in TEST_USERS
  is ONLY for tests that do not exercise ownership. Ownership-gated
  tests must mint headers via make_athlete_headers(athlete["id"]).
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
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def officer_headers_secondary():
    return TEST_USERS["officer_headers_secondary"]


@pytest.fixture
def officer_headers_tertiary():
    return TEST_USERS["officer_headers_tertiary"]


@pytest.fixture
def coach_headers():
    return TEST_USERS["coach_headers"]


@pytest.fixture
def coach_headers_secondary():
    return TEST_USERS["coach_headers_secondary"]


@pytest.fixture
def booster_headers():
    return TEST_USERS["booster_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Entity-backed Athlete fallback — ONLY safe when ownership is NOT
# exercised. Ownership-gated calls MUST mint via make_athlete_headers.
# ---------------------------------------------------------------------------
@pytest.fixture
def athlete_fallback_headers():
    return TEST_USERS["athlete_headers"]
