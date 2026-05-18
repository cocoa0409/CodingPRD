"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- PlatformAdmin / LoanOfficer / FinanceManager / CollectionsAgent are
  OPAQUE — shared *_headers constants are canonical.
- Customer is ENTITY-BACKED. The fallback header in TEST_USERS is
  ONLY for tests that do not exercise ownership. Ownership-gated
  Customer tests must mint headers via make_customer_headers(c["id"])
  using the actual Customer.id returned by POST /customers.
"""
from __future__ import annotations

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle owned by the
    runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    """Best-effort wipe of the implementation's in-memory store
    between tests. Implementations that do not expose
    /__test__/reset are tolerated; tests still pass as long as they
    create unique entities."""
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
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def loan_officer_headers():
    return TEST_USERS["loan_officer_headers"]


@pytest.fixture
def finance_manager_headers():
    return TEST_USERS["finance_manager_headers"]


@pytest.fixture
def collections_agent_headers():
    return TEST_USERS["collections_agent_headers"]


# ---------------------------------------------------------------------------
# Entity-backed fallback header — ONLY safe when ownership is NOT
# exercised. Ownership-gated Customer calls MUST mint per-instance
# headers via make_customer_headers(customer["id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def customer_fallback_headers():
    return TEST_USERS["customer_fallback_headers"]
