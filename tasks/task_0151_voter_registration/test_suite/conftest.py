"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1: operator roles (ElectionBoard, RegistrarClerk, ReviewerClerk,
PrecinctOfficer, TestDriver) are opaque-id; Voter is entity_backed by
Voter. The shared *_headers constants below are appropriate for tests
that don't depend on a specific Voter.id ownership match (e.g., auth
probes, role-forbidden probes). Tests that need a real Voter's
identity should construct headers via make_voter_headers(voter_id)
from test_helpers.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    parse_iso,
    reset_clock_tracker_to,
    utcnow,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle owned by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    """Best-effort wipe of the implementation's in-memory store between
    tests. Implementations that do not expose /__test__/reset are
    tolerated; tests still pass as long as they create unique entities.

    After a reset the test-process's logical-clock tracker is also
    reset so absolute timestamps are anchored to the server's `now`
    (if reported) or wall-clock now otherwise.
    """
    impl_now = None
    try:
        resp = api_client._request(
            "POST", "/__test__/reset", None,
            TEST_USERS["test_driver_headers"],
        )
        try:
            body = resp.json()
            data = body.get("data") if isinstance(body, dict) else None
            if isinstance(data, dict) and data.get("now"):
                impl_now = parse_iso(data["now"])
        except Exception:
            impl_now = None
    except Exception:
        pass
    reset_clock_tracker_to(impl_now if impl_now is not None else utcnow())
    yield


# ---------------------------------------------------------------------------
# Per-role shared-constant headers — PRD §2.1.
# These are appropriate ONLY for tests that don't fire an ownership
# check on Voter. For Voter ownership tests, build headers from
# make_voter_headers(voter_id).
# ---------------------------------------------------------------------------
@pytest.fixture
def election_board_headers():
    return TEST_USERS["election_board_headers"]


@pytest.fixture
def registrar_clerk_headers():
    return TEST_USERS["registrar_clerk_headers"]


@pytest.fixture
def reviewer_clerk_headers():
    return TEST_USERS["reviewer_clerk_headers"]


@pytest.fixture
def precinct_officer_headers():
    return TEST_USERS["precinct_officer_headers"]


@pytest.fixture
def voter_headers():
    return TEST_USERS["voter_headers"]


@pytest.fixture
def test_driver_headers():
    return TEST_USERS["test_driver_headers"]
