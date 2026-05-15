"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- PlatformAdmin, CreativeReviewer, ExchangeService, MeasurementPartner,
  AntiFraudService are OPAQUE — shared TEST_USERS constants are
  canonical.
- AccountOwner, CampaignManager, FinanceOfficer are ENTITY-BACKED
  (X-User-ID == AccountUser.external_user_id). Tests that exercise
  ownership MUST mint headers via make_account_owner_headers /
  make_campaign_manager_headers / make_finance_officer_headers with the
  AccountUser's external_user_id, not the shared fallback constants.
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
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def platform_admin_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


@pytest.fixture
def creative_reviewer_headers():
    return TEST_USERS["creative_reviewer_headers"]


@pytest.fixture
def creative_reviewer_headers_alt():
    return TEST_USERS["creative_reviewer_headers_alt"]


@pytest.fixture
def creative_reviewer_headers_third():
    return TEST_USERS["creative_reviewer_headers_third"]


@pytest.fixture
def exchange_service_headers():
    return TEST_USERS["exchange_service_headers"]


@pytest.fixture
def measurement_partner_headers():
    return TEST_USERS["measurement_partner_headers"]


@pytest.fixture
def anti_fraud_service_headers():
    return TEST_USERS["anti_fraud_service_headers"]


# ---------------------------------------------------------------------------
# Entity-backed fallbacks — ONLY for tests that do not exercise
# ownership (PRD §2.1). Ownership-gated calls MUST mint per-instance
# headers via the make_*_headers builders.
# ---------------------------------------------------------------------------
@pytest.fixture
def account_owner_fallback_headers():
    return TEST_USERS["account_owner_headers"]


@pytest.fixture
def campaign_manager_fallback_headers():
    return TEST_USERS["campaign_manager_headers"]


@pytest.fixture
def finance_officer_fallback_headers():
    return TEST_USERS["finance_officer_headers"]
