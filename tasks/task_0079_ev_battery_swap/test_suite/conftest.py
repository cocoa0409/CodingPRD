"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires per-role headers and the session-scoped api client.

PRD §2.1 identity rules:
- Member is entity_backed → ownership-gated tests MUST use
  make_member_headers(member['id']).
- StationOperator is entity_backed on Station → operator calls MUST use
  make_operator_headers(station['id']).
- PlatformAdmin is opaque → shared constants are canonical.
"""
from __future__ import annotations
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# ---------------------------------------------------------------------------
# Opaque PlatformAdmin headers — shared constants are canonical.
# ---------------------------------------------------------------------------
@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def platform_admin_headers_alt():
    """Second PlatformAdmin id; useful where two distinct admin actor_ids
    are needed (e.g., audit-log actor_id discrimination)."""
    return TEST_USERS["platform_admin_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed fallback headers — use ONLY for tests that do not exercise
# ownership (missing-auth, wrong-role, missing-resource). Ownership-gated
# tests must call make_member_headers / make_operator_headers from
# test_helpers with the real entity id.
# ---------------------------------------------------------------------------
@pytest.fixture
def member_fallback_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def operator_fallback_headers():
    return TEST_USERS["operator_headers"]
