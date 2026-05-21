"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1: AccountHolder is entity_backed by Account. The shared
account_holder_headers constant is appropriate only for tests that do
NOT depend on ownership of a specific Account.id (e.g., auth probes,
role-forbidden probes). Tests that need ownership-gated access build
headers via make_account_holder_headers(account_id).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    reset_clock_tracker_to,
    utcnow,
)
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
            "POST", "/__test__/reset", None,
            TEST_USERS["agency_admin_headers"],
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
# Per-role shared headers — for tests that do NOT exercise ownership.
# ---------------------------------------------------------------------------
@pytest.fixture
def account_holder_headers():
    return TEST_USERS["account_holder_headers"]


@pytest.fixture
def agency_admin_headers():
    return TEST_USERS["agency_admin_headers"]


@pytest.fixture
def gantry_operator_headers():
    return TEST_USERS["gantry_operator_headers"]
