"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- PlanAdministrator / ClaimAdjudicator / Auditor are OPAQUE — shared
  *_headers constants are canonical.
- AccountHolder is ENTITY-BACKED. The fallback header in TEST_USERS is
  ONLY for tests that do not exercise ownership. Ownership-gated tests
  must mint headers via make_account_holder_headers(account_holder["id"])
  using the actual entity ids returned by the create endpoints.
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
            TEST_USERS["plan_admin_headers"],
        )
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — shared constants canonical (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def plan_admin_headers():
    return TEST_USERS["plan_admin_headers"]


@pytest.fixture
def plan_admin_headers_alt():
    return TEST_USERS["plan_admin_headers_alt"]


@pytest.fixture
def adjudicator_headers():
    return TEST_USERS["adjudicator_headers"]


@pytest.fixture
def adjudicator_headers_alt():
    return TEST_USERS["adjudicator_headers_alt"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Entity-backed fallback header — ONLY safe when ownership is NOT
# exercised. Ownership-gated calls MUST mint per-instance headers via
# make_account_holder_headers(account_holder["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def account_holder_fallback_headers():
    return TEST_USERS["account_holder_fallback_headers"]
