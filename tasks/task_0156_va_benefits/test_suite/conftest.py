"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1: the Veteran role is entity-backed. Shared *_headers constants
below are safe ONLY for tests that don't depend on the caller owning a
specific Veteran.id (auth probes, RBAC probes, 404 probes). Tests that
need a real Veteran's identity should construct headers via
make_veteran_headers(veteran_id) from test_helpers.
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
    """
    impl_now = None
    for path in ("/__test__/reset", "/_test/reset"):
        try:
            resp = api_client._request(
                "POST", path, None,
                TEST_USERS["platform_admin_headers"],
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
# Per-role headers — PRD §2.1.
# Shared constants only; tests that need entity-backed Veteran identity
# build headers via make_veteran_headers.
# ---------------------------------------------------------------------------
@pytest.fixture
def veteran_headers():
    return TEST_USERS["veteran_headers"]


@pytest.fixture
def va_clerk_headers():
    return TEST_USERS["va_clerk_headers"]


@pytest.fixture
def va_clerk_2_headers():
    return TEST_USERS["va_clerk_2_headers"]


@pytest.fixture
def rater_headers():
    return TEST_USERS["rater_headers"]


@pytest.fixture
def rater_2_headers():
    return TEST_USERS["rater_2_headers"]


@pytest.fixture
def rater_3_headers():
    return TEST_USERS["rater_3_headers"]


@pytest.fixture
def counselor_headers():
    return TEST_USERS["counselor_headers"]


@pytest.fixture
def counselor_2_headers():
    return TEST_USERS["counselor_2_headers"]


@pytest.fixture
def counselor_3_headers():
    return TEST_USERS["counselor_3_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
