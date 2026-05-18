"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1: every role is entity-backed by Member. The shared *_headers
constants below are appropriate for tests that don't depend on ownership
of a specific Member.id (e.g., auth probes, role-forbidden probes).
Tests that need a seated Member's identity should construct headers via
make_<role>_headers(member_id) from test_helpers.
"""
from __future__ import annotations

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client, reset_clock_tracker_to, utcnow
from test_helpers.factories import parse_iso


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
    reset so absolute timestamps are anchored to wall-clock now.
    """
    impl_now = None
    try:
        resp = api_client._request(
            "POST", "/hoa/__test__/reset", None,
            TEST_USERS["president_role_headers"],
        )
        try:
            body = resp.json()
            data = body.get("data") if isinstance(body, dict) else None
            if isinstance(data, dict) and data.get("now"):
                impl_now = parse_iso(data["now"])
        except Exception:
            impl_now = None
    except Exception:
        try:
            api_client._request(
                "POST", "/__test__/reset", None,
                TEST_USERS["president_role_headers"],
            )
        except Exception:
            pass
    reset_clock_tracker_to(impl_now if impl_now is not None else utcnow())
    yield


# ---------------------------------------------------------------------------
# Per-role headers — PRD §2.1. Shared constants only; tests that need
# seated-Member identity build headers from test_helpers builders.
# ---------------------------------------------------------------------------
@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def secretary_role_headers():
    return TEST_USERS["secretary_role_headers"]


@pytest.fixture
def treasurer_role_headers():
    return TEST_USERS["treasurer_role_headers"]


@pytest.fixture
def president_role_headers():
    return TEST_USERS["president_role_headers"]


@pytest.fixture
def director_role_headers():
    return TEST_USERS["director_role_headers"]
