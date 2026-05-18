"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- BureauOperator / CFPBOperator / PlatformAdmin are OPAQUE — shared
  *_headers constants are canonical.
- Consumer and Furnisher are ENTITY-BACKED. The fallback headers in
  TEST_USERS are ONLY for tests that do not exercise ownership.
  Ownership-gated tests must mint headers via
  make_consumer_headers(consumer["id"]) or
  make_furnisher_headers(furnisher["id"]) using the actual entity ids
  returned by the create endpoints.
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
        api_client._request(
            "POST", "/__test__/reset", None,
            TEST_USERS["platform_admin_headers"],
        )
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — shared constants canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def bureau_operator_headers():
    return TEST_USERS["bureau_operator_headers"]


@pytest.fixture
def bureau_operator_headers_alt():
    return TEST_USERS["bureau_operator_headers_alt"]


@pytest.fixture
def cfpb_operator_headers():
    return TEST_USERS["cfpb_operator_headers"]


@pytest.fixture
def cfpb_operator_headers_alt():
    return TEST_USERS["cfpb_operator_headers_alt"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Entity-backed fallback headers — ONLY safe when ownership is NOT
# exercised. Ownership-gated calls MUST mint per-instance headers via
# make_consumer_headers(consumer["id"]) or
# make_furnisher_headers(furnisher["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def consumer_fallback_headers():
    return TEST_USERS["consumer_fallback_headers"]


@pytest.fixture
def furnisher_fallback_headers():
    return TEST_USERS["furnisher_fallback_headers"]
