"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1: five of the six roles are entity-backed. The shared *_headers
constants below are appropriate for tests that don't depend on ownership
of a specific entity (auth probes, role-forbidden probes). Tests that
need a specific entity's identity should construct headers via
make_<role>_headers(entity_id) from test_helpers.
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
    tests. Implementations that don't expose /__test__/reset are
    tolerated; tests still pass as long as they create unique entities.

    After a reset the test-process's logical-clock tracker is also reset
    so absolute timestamps are anchored to wall-clock now.
    """
    impl_now = None
    for path in (
        "/housing-voucher/__test__/reset",
        "/__test__/reset",
    ):
        try:
            resp = api_client._request(
                "POST", path, None, TEST_USERS["pha_admin_headers"],
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
# Per-role shared header fixtures — PRD §2.1
# ---------------------------------------------------------------------------
@pytest.fixture
def pha_admin_headers():
    return TEST_USERS["pha_admin_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def landlord_headers():
    return TEST_USERS["landlord_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def case_worker_headers():
    return TEST_USERS["case_worker_headers"]


@pytest.fixture
def portability_coordinator_headers():
    return TEST_USERS["portability_coordinator_headers"]
