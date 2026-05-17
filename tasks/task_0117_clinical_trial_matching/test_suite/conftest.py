"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- PrincipalInvestigator, IRBReviewer, StudyCoordinator are OPAQUE —
  shared TEST_USERS headers are canonical.
- Participant_self is ENTITY-BACKED. The fallback header in TEST_USERS
  is ONLY for tests that do not exercise ownership. Ownership-gated
  tests must mint headers via
  make_participant_self_headers(participant["id"]).
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
    tolerated; tests still pass as long as they create unique entities."""
    try:
        api_client._request("POST", "/__test__/reset", None, {})
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — shared constants canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def pi_headers():
    return TEST_USERS["pi_headers"]


@pytest.fixture
def pi_headers_alt():
    return TEST_USERS["pi_headers_alt"]


@pytest.fixture
def irb_reviewer_headers():
    return TEST_USERS["irb_reviewer_headers"]


@pytest.fixture
def irb_reviewer_headers_alt():
    return TEST_USERS["irb_reviewer_headers_alt"]


@pytest.fixture
def study_coordinator_headers():
    return TEST_USERS["study_coordinator_headers"]


@pytest.fixture
def study_coordinator_headers_alt():
    return TEST_USERS["study_coordinator_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed fallback header — ONLY safe when ownership is NOT
# exercised. Ownership-gated calls MUST mint per-instance headers via
# make_participant_self_headers(participant["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def participant_self_fallback_headers():
    return TEST_USERS["participant_self_fallback_headers"]
