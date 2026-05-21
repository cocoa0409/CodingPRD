"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1: the Claimant role is entity-backed. Shared *_headers constants
below are safe ONLY for tests that don't depend on the caller owning a
specific Claimant.id (auth probes, RBAC probes, 404 probes). Tests that
need a real Claimant's identity should construct headers via
make_claimant_headers(claimant_id) from test_helpers.
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
    in that case we MUST NOT clobber the helper's clock tracker, because
    the server's logical clock (PRD §2.10) is monotonically non-decreasing
    and retains every prior advance across tests. Resetting the helper to
    wall-clock time while the server holds a far-future logical_now would
    desynchronise every subsequent slot.start_at computation, causing
    seemingly-future booking windows to land in the server's past.
    """
    impl_reset_succeeded = False
    impl_now = None
    for path in ("/__test__/reset", "/_test/reset"):
        try:
            resp = api_client._request(
                "POST", path, None,
                TEST_USERS["platform_admin_headers"],
            )
            # Accept only an HTTP 2xx as a real reset success.
            if 200 <= resp.status_code < 300:
                impl_reset_succeeded = True
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
    if impl_reset_succeeded:
        # Reset endpoint exists and accepted the request — sync helper to
        # whatever clock the impl reports (or wall time if it doesn't say).
        reset_clock_tracker_to(impl_now if impl_now is not None else utcnow())
    # Else: leave the helper's clock tracker alone so it continues to
    # mirror the server's monotonic logical clock.
    yield


# ---------------------------------------------------------------------------
# Per-role headers — PRD §2.1.
# Shared constants only; tests that need entity-backed Claimant identity
# build headers via make_claimant_headers.
# ---------------------------------------------------------------------------
@pytest.fixture
def claimant_headers():
    return TEST_USERS["claimant_headers"]


@pytest.fixture
def dds_examiner_headers():
    return TEST_USERS["dds_examiner_headers"]


@pytest.fixture
def dds_examiner_2_headers():
    return TEST_USERS["dds_examiner_2_headers"]


@pytest.fixture
def alj_headers():
    return TEST_USERS["alj_headers"]


@pytest.fixture
def alj_2_headers():
    return TEST_USERS["alj_2_headers"]


@pytest.fixture
def appeals_council_headers():
    return TEST_USERS["appeals_council_headers"]


@pytest.fixture
def cdr_reviewer_headers():
    return TEST_USERS["cdr_reviewer_headers"]


@pytest.fixture
def cdr_reviewer_2_headers():
    return TEST_USERS["cdr_reviewer_2_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
