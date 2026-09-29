"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_cashier_headers,
    make_clerk_headers,
    make_manager_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def treasury_headers():
    """TreasuryAnalyst — registers stores, commissions safes, posts bank credits."""
    return TEST_USERS["treasury_headers"]


@pytest.fixture
def clerk_headers():
    """CashOfficeClerk U-CLERK-1 — the cash room's primary operator."""
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def clerk_2_headers():
    """CashOfficeClerk U-CLERK-2 — the second pair of hands for dual control."""
    return TEST_USERS["clerk_2_headers"]


@pytest.fixture
def clerk_3_headers():
    """CashOfficeClerk U-CLERK-3 — the till counter."""
    return TEST_USERS["clerk_3_headers"]


@pytest.fixture
def clerk_4_headers():
    """CashOfficeClerk U-CLERK-4 — a fourth distinct clerk identity."""
    return TEST_USERS["clerk_4_headers"]


@pytest.fixture
def manager_headers():
    """StoreManager — enrolls cashiers, voids deposits, decides change orders."""
    return TEST_USERS["manager_headers"]


@pytest.fixture
def manager_2_headers():
    """A second StoreManager identity."""
    return TEST_USERS["manager_2_headers"]


@pytest.fixture
def carrier_headers():
    """ArmoredCarrier — signs for sealed bags."""
    return TEST_USERS["carrier_headers"]


@pytest.fixture
def investigator_headers():
    """LossPreventionInvestigator — restores posture, closes escalated cases."""
    return TEST_USERS["investigator_headers"]


@pytest.fixture
def cashier_headers():
    """Cashier with an identifier bound to no Cashier record.

    Only for tests that do not exercise cashier ownership; ownership-gated calls
    must use make_cashier_headers(cashier["id"]).
    """
    return TEST_USERS["cashier_headers"]


@pytest.fixture
def headers_for():
    """Factory returning per-identity headers for the roles tests need to vary."""
    return {
        "cashier": make_cashier_headers,
        "clerk": make_clerk_headers,
        "manager": make_manager_headers,
    }
