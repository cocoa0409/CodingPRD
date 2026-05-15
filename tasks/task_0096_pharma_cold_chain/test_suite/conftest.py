"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1: all five roles are opaque — shared TEST_USERS constants are
canonical. Per-instance builders (make_<role>_headers) are exposed
from test_helpers for SOD chains where a test needs to thread a
specific X-User-ID through one step.
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
    """Best-effort wipe of the implementation's in-memory store between
    tests. Implementations that do not expose /__test__/reset are
    tolerated; tests still pass as long as they create unique entities.
    """
    try:
        api_client._request("POST", "/__test__/reset", None, {})
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — shared constants canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def warehouse_admin_headers():
    return TEST_USERS["warehouse_admin_headers"]


@pytest.fixture
def warehouse_admin_headers_alt():
    return TEST_USERS["warehouse_admin_headers_alt"]


@pytest.fixture
def receiver_headers():
    return TEST_USERS["receiver_headers"]


@pytest.fixture
def receiver_headers_alt():
    return TEST_USERS["receiver_headers_alt"]


@pytest.fixture
def qa_officer_headers():
    return TEST_USERS["qa_officer_headers"]


@pytest.fixture
def qa_officer_headers_alt():
    return TEST_USERS["qa_officer_headers_alt"]


@pytest.fixture
def qa_officer_headers_third():
    return TEST_USERS["qa_officer_headers_third"]


@pytest.fixture
def picker_headers():
    return TEST_USERS["picker_headers"]


@pytest.fixture
def picker_headers_alt():
    return TEST_USERS["picker_headers_alt"]


@pytest.fixture
def recall_officer_headers():
    return TEST_USERS["recall_officer_headers"]


@pytest.fixture
def recall_officer_headers_alt():
    return TEST_USERS["recall_officer_headers_alt"]
