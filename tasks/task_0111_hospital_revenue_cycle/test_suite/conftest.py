"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1 — all five roles are opaque. X-User-ID is audit data; no
ownership check is performed against it. Shared header constants are
canonical for every call.
"""
from __future__ import annotations

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle owned by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    """Best-effort wipe of any in-memory state between tests.
    Implementations that do not expose /__test__/reset are tolerated;
    tests still pass as long as they create unique entities.
    """
    try:
        api_client._request("POST", "/__test__/reset", None, {})
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Role headers — all roles are opaque per PRD §2.1.
# ---------------------------------------------------------------------------
@pytest.fixture
def registration_clerk_headers():
    return TEST_USERS["registration_clerk_headers"]


@pytest.fixture
def registration_clerk_headers_alt():
    return TEST_USERS["registration_clerk_headers_alt"]


@pytest.fixture
def charge_capture_clerk_headers():
    return TEST_USERS["charge_capture_clerk_headers"]


@pytest.fixture
def charge_capture_clerk_headers_alt():
    return TEST_USERS["charge_capture_clerk_headers_alt"]


@pytest.fixture
def coder_headers():
    return TEST_USERS["coder_headers"]


@pytest.fixture
def coder_headers_alt():
    return TEST_USERS["coder_headers_alt"]


@pytest.fixture
def biller_headers():
    return TEST_USERS["biller_headers"]


@pytest.fixture
def biller_headers_alt():
    return TEST_USERS["biller_headers_alt"]


@pytest.fixture
def test_harness_headers():
    return TEST_USERS["test_harness_headers"]
