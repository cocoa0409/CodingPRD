"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1: the Claimant and EmployerAgent roles are entity-backed.
Shared *_headers constants below are safe ONLY for tests that don't
depend on the caller owning a specific entity (auth probes, RBAC
probes, 404 probes). Tests that need a real Claimant's identity
should construct headers via make_claimant_headers(claimant_id);
similarly make_employer_agent_headers for EmployerAgent.
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
    tests. Implementations that do not expose a reset hook are tolerated;
    tests still pass as long as they create unique entities.

    After a reset the test-process's logical-clock tracker is also
    reset so absolute timestamps are anchored to wall-clock now.
    """
    impl_now = None
    for path in ("/__test__/reset", "/_test/reset", "/_clock/reset"):
        try:
            resp = api_client._request(
                "POST", path, None,
                TEST_USERS["system_admin_headers"],
            )
            try:
                body = resp.json()
                data = body.get("data") if isinstance(body, dict) else None
                if isinstance(data, dict) and data.get("now"):
                    impl_now = parse_iso(data["now"])
            except Exception:
                impl_now = None
            break
        except Exception:
            continue
    reset_clock_tracker_to(impl_now if impl_now is not None else utcnow())
    yield


# ---------------------------------------------------------------------------
# Per-role headers — PRD §2.1. Shared constants only; tests that need
# entity-backed Claimant/EmployerAgent identity build headers via
# make_claimant_headers / make_employer_agent_headers.
# ---------------------------------------------------------------------------
@pytest.fixture
def claimant_headers():
    return TEST_USERS["claimant_headers"]


@pytest.fixture
def employer_agent_headers():
    return TEST_USERS["employer_agent_headers"]


@pytest.fixture
def adjudicator_headers():
    return TEST_USERS["adjudicator_headers"]


@pytest.fixture
def appeal_officer_headers():
    return TEST_USERS["appeal_officer_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]
