"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and the server lifecycle. This conftest
wires per-role shared headers and the session-scoped API client.

PRD §2.1: Customer and Driver are entity-backed roles; the shared
*_headers constants below are appropriate ONLY for tests that don't
exercise ownership on those roles (auth probes, role-forbidden probes,
404 probes). Tests that need a real Customer's or Driver's identity
must build headers via make_customer_headers/make_driver_headers from
test_helpers.
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
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    """Best-effort reset between tests. Implementations that expose a
    /__test__/reset endpoint can use it to wipe state; absent that,
    tests still pass as long as they create unique entities.

    After reset, the in-process logical-clock tracker is re-anchored
    to the implementation's clock if it reports one. PRD §2.11
    'The clock is forward-only' — when no reset is available the
    in-process tracker is left monotonically forward (only advanced,
    never rewound), so subsequent tests honor the server's current
    notion of time even though earlier tests pushed it forward.
    """
    impl_now = None
    try:
        resp = api_client._request(
            "POST", "/__test__/reset", None,
            TEST_USERS["dispatcher_headers"],
        )
        if 200 <= resp.status_code < 300:
            try:
                body = resp.json()
                data = body.get("data") if isinstance(body, dict) else None
                if isinstance(data, dict) and data.get("now"):
                    impl_now = parse_iso(data["now"])
            except Exception:
                impl_now = None
    except Exception:
        pass
    if impl_now is not None:
        reset_clock_tracker_to(impl_now)
    # else: leave the in-process tracker at its current monotonic
    # high-water mark so the next test's relative advances move the
    # server clock strictly forward (PRD §2.11 forward-only).
    yield


# ---------------------------------------------------------------------------
# Shared per-role headers — see test_helpers/test_users.py.
# ---------------------------------------------------------------------------
@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def driver_headers():
    return TEST_USERS["driver_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def sorting_hub_operator_headers():
    return TEST_USERS["sorting_hub_operator_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]
