"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start, readiness, shutdown) is managed by the
prd-bench-local-runner framework. PYTHONPATH points at the parent
directory so `test_helpers` is importable directly.
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
    """Session-scoped API client. Base URL supplied by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_server_state():
    """Reset in-memory server state before every test so each test
    starts from a clean slate. The /_test/reset endpoint is a test-only
    hook on the server (not part of PRD); if the implementation does
    not provide it, tests fall back to creating fresh fleet rows
    per-test (every fixture mints a new fleet)."""
    try:
        api_client._request(
            "POST",
            "/_test/reset",
            None,
            TEST_USERS["fleet_admin_headers"],
        )
    except Exception:
        # Server may not implement /_test/reset; if not, tests still
        # work because every helper mints its own Fleet.
        pass
    yield


# --- Role headers (PRD section 2.1: all three roles use opaque X-User-ID) --
@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def operator_headers_alt():
    return TEST_USERS["operator_headers_alt"]


@pytest.fixture
def fleet_admin_headers():
    return TEST_USERS["fleet_admin_headers"]


@pytest.fixture
def fleet_admin_headers_alt():
    return TEST_USERS["fleet_admin_headers_alt"]


@pytest.fixture
def wms_headers():
    return TEST_USERS["wms_headers"]
