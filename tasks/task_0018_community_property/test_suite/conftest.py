"""Pytest fixtures exposing test_helpers infrastructure.

PYTHONPATH is set by prd-bench-local-runner so `test_helpers` resolves without any
sys.path hacks. Server lifecycle is also the runner's job — this file only wires up
lightweight fixtures and role headers.
"""

from datetime import datetime, timezone

import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
    advance_clock_to,
    iso_utc,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_logical_clock_to_wall_time():
    """Pin the server's logical clock to current wall time before every test.

    The implementation's now() is the logical clock (PRD §2.10, §3.10 — settable
    only via POST /_clock/advance). When test A advances the clock far into the
    future to drive an auto-transition, test B's "future" timestamps computed
    from datetime.now(timezone.utc) (wall time) become past relative to the
    server's persisted logical clock, producing spurious ERR_SLOT_IN_PAST and
    ERR_VOTING_WINDOW_INVALID. This autouse fixture resets the logical clock
    to current wall time before every test so wall-time-based timestamps are
    always future from the server's perspective.

    This is a test-hygiene fix, not a PRD relaxation: tests that need to advance
    the clock still call advance_clock_to() explicitly within their body.
    """
    advance_clock_to(iso_utc(datetime.now(timezone.utc)))
    yield


# ──────────────────────────────────────────────────────────
# Shared-constant role headers — for tests that do NOT exercise ownership.
# Ownership-gated tests construct headers via make_<role>_headers(<actual-id>) directly.
# ──────────────────────────────────────────────────────────

@pytest.fixture
def property_manager_headers():
    return TEST_USERS["property_manager_headers"]


@pytest.fixture
def maintenance_headers():
    return TEST_USERS["maintenance_headers"]


@pytest.fixture
def committee_chair_headers():
    return TEST_USERS["committee_chair_headers"]


@pytest.fixture
def owner_headers():
    """Fallback Owner headers — only safe for tests that do NOT exercise ownership."""
    return TEST_USERS["owner_headers"]
