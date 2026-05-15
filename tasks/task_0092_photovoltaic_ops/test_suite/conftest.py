"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1: all four roles carry opaque identities — shared constants
are canonical. Per-instance builders exist in test_helpers for tests
that must distinguish two actors (patrol SoD, concurrent ack race).
"""
from __future__ import annotations

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    """Wipe the implementation's in-memory store before each test so
    catalog state cannot leak across tests. The /__test__/reset
    endpoint is a test-infrastructure extension parallel to PRD §3.2's
    test-only hooks; a 404 from an implementation that does not expose
    it is tolerated."""
    try:
        api_client._request("POST", "/__test__/reset", None, {})
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — shared constants canonical (PRD §2.1)
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def admin_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


@pytest.fixture
def om_headers():
    return TEST_USERS["om_engineer_headers"]


@pytest.fixture
def om_headers_alt():
    return TEST_USERS["om_engineer_headers_alt"]


@pytest.fixture
def field_headers():
    return TEST_USERS["field_operator_headers"]


@pytest.fixture
def field_headers_alt():
    return TEST_USERS["field_operator_headers_alt"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def finance_headers_alt():
    return TEST_USERS["finance_officer_headers_alt"]
