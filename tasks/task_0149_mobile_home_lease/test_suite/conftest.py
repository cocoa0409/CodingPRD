"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1: ParkManager and Resident are entity-backed. The shared
*_headers constants are appropriate for auth/RBAC probes and 404
probes; ownership-gated tests build headers via make_<role>_headers()
in test_helpers.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
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
    """
    for endpoint in ("/__test__/reset", "/_test/reset"):
        try:
            api_client._request(
                "POST", endpoint, None,
                TEST_USERS["platform_admin_headers"],
            )
            break
        except Exception:
            continue
    yield


# ---------------------------------------------------------------------------
# Per-role shared headers — auth/RBAC probes and non-ownership reads.
# ---------------------------------------------------------------------------
@pytest.fixture
def park_manager_headers():
    return TEST_USERS["park_manager_headers"]


@pytest.fixture
def resident_headers():
    return TEST_USERS["resident_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
