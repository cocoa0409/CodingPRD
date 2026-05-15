"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- AdminOps, PaymentAdapter, LogisticsAdapter, VetAdapter are OPAQUE →
  shared constants are canonical.
- Customer is entity_backed → ownership-gated tests MUST use
  make_customer_headers(customer['id']) (provided via the
  setup_* fixtures in test_helpers).
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
    catalog state (recipes, warehouses, inventory) from a previous test
    cannot leak into this one. The /__test__/reset endpoint is a
    test-infrastructure extension (parallel to the test-driver
    endpoints in PRD §3.7); a 404 from an implementation that does not
    expose it is tolerated for backward compatibility."""
    try:
        api_client._request("POST", "/__test__/reset", None, {})
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers (canonical via shared constants)
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_ops_headers():
    return TEST_USERS["admin_ops_headers"]


@pytest.fixture
def admin_ops_headers_alt():
    return TEST_USERS["admin_ops_headers_alt"]


@pytest.fixture
def payment_adapter_headers():
    return TEST_USERS["payment_adapter_headers"]


@pytest.fixture
def logistics_adapter_headers():
    return TEST_USERS["logistics_adapter_headers"]


@pytest.fixture
def vet_adapter_headers():
    return TEST_USERS["vet_adapter_headers"]


@pytest.fixture
def customer_fallback_headers():
    """PRD §2.1: a Customer-role header whose X-User-ID matches no real
    Customer. Use ONLY for tests that do NOT exercise ownership
    (missing-auth, wrong-role, missing-resource). For ownership-gated
    tests, use the entity-backed setup_* fixtures in test_helpers."""
    return TEST_USERS["customer_headers"]
