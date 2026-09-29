"""Pytest fixtures exposing the `test_helpers` infrastructure.

The runner owns the server lifecycle, `API_BASE_URL` and `PYTHONPATH`, so
`test_helpers` is importable without any path manipulation here.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# ─── Opaque operator identities ───────────────────────────────────────────────

@pytest.fixture
def credit_officer_headers():
    """The primary `CreditOfficer`, `co_1`."""
    return TEST_USERS["credit_officer_headers"]


@pytest.fixture
def second_credit_officer_headers():
    """A second `CreditOfficer`, `co_2`, for the four-eyes gates."""
    return TEST_USERS["second_credit_officer_headers"]


@pytest.fixture
def collateral_analyst_headers():
    """The primary `CollateralAnalyst`, `ca_1`."""
    return TEST_USERS["collateral_analyst_headers"]


@pytest.fixture
def second_collateral_analyst_headers():
    """A second `CollateralAnalyst`, `ca_2`."""
    return TEST_USERS["second_collateral_analyst_headers"]


@pytest.fixture
def wire_operator_headers():
    """The primary `WireOperator`, `wo_1`."""
    return TEST_USERS["wire_operator_headers"]


@pytest.fixture
def second_wire_operator_headers():
    """A second `WireOperator`, `wo_2`."""
    return TEST_USERS["second_wire_operator_headers"]


# ─── Entity-backed identities that resolve to no row at all ───────────────────

@pytest.fixture
def unresolvable_borrower_headers():
    """A `Borrower` identity that resolves to no facility row."""
    return TEST_USERS["unresolvable_borrower_headers"]


@pytest.fixture
def unresolvable_custodian_headers():
    """A `Custodian` identity that resolves to no custodian row."""
    return TEST_USERS["unresolvable_custodian_headers"]


@pytest.fixture
def unresolvable_investor_headers():
    """An `Investor` identity that resolves to no investor row."""
    return TEST_USERS["unresolvable_investor_headers"]
