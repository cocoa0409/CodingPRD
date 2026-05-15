"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just wires
per-role headers and the session-scoped api client.

PRD §2.1 identity rules:
- RiskOfficer / ComplianceOfficer / SettlementOperator / MarketDataSystem
  are opaque → shared constants are canonical.
- Trader is entity_backed → ownership-gated tests MUST mint headers via
  make_trader_headers(trader["id"]) from test_helpers.test_users.
"""
from __future__ import annotations
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(autouse=True)
def _reset_server_state_between_tests():
    """Reset the implementation's in-memory store before every test.

    Calls the test-only POST /fx-risk/_test/reset endpoint (analogous to
    PRD §2.12's `_clock/advance` test-driving capability). This isolates
    each test so that entities with unique fields (currency-pair `code`,
    trader name, counterparty name, settlement idempotency key) do not
    bleed across tests.
    """
    api_client.reset_test_state()
    yield


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# ---------------------------------------------------------------------------
# Opaque-role headers (canonical via shared constants)
# ---------------------------------------------------------------------------
@pytest.fixture
def risk_officer_headers():
    return TEST_USERS["risk_officer_headers"]


@pytest.fixture
def risk_officer_headers_alt():
    """A second RiskOfficer id — useful when a test needs two distinct
    risk-officer actors (e.g., approve vs override of the same chain)."""
    return TEST_USERS["risk_officer_headers_alt"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def settlement_operator_headers():
    return TEST_USERS["settlement_operator_headers"]


@pytest.fixture
def settlement_operator_headers_alt():
    return TEST_USERS["settlement_operator_headers_alt"]


@pytest.fixture
def market_data_headers():
    return TEST_USERS["market_data_headers"]


@pytest.fixture
def trader_fallback_headers():
    """Fallback Trader headers — X-User-ID 'trader-fallback'.

    PRD §2.1: real Trader X-User-ID MUST equal an existing Trader.id.
    This constant matches no real trader, so use ONLY for tests that do
    NOT exercise ownership (missing-resource, wrong-role, raw input
    validation, ERR_AUTH/ERR_FORBIDDEN scenarios).
    """
    return TEST_USERS["trader_headers"]
