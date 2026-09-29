"""Pytest bridge: exposes the ``test_helpers`` infrastructure as fixtures.

The runner puts the task directory on ``PYTHONPATH`` and relaunches the API
server before every individual test, so every fixture here is function-scoped
and every precondition is rebuilt from scratch through published endpoints.
"""

import pytest

from test_helpers import TEST_USERS
from test_helpers.fixtures import (  # noqa: F401  (re-exported as fixtures)
    accrual_and_collected_setup,
    active_commitment,
    active_contract,
    api,
    clock,
    contract_with_item,
    draft_contract,
    dual_variant_setup,
    elected_commitment,
    holdback_two_member_setup,
    loaded_ledger_setup,
    member,
    per_line_fee_setup,
    priced_setup,
    priced_setup_with_unmatched_item,
    revision_cycle_setup,
    watchlist_chain_setup,
)
from test_helpers.test_users import (
    clinical_reviewer_2_headers,
    clinical_reviewer_headers,
    compliance_analyst_headers,
    contract_manager_2_headers,
    contract_manager_headers,
    distributor_agent_headers,
    finance_administrator_headers,
)


@pytest.fixture
def test_users():
    """The fixed operator identities every test acts as."""
    return TEST_USERS


@pytest.fixture
def cm_headers():
    return contract_manager_headers()


@pytest.fixture
def cm2_headers():
    return contract_manager_2_headers()


@pytest.fixture
def reviewer_headers():
    return clinical_reviewer_headers()


@pytest.fixture
def reviewer2_headers():
    return clinical_reviewer_2_headers()


@pytest.fixture
def analyst_headers():
    return compliance_analyst_headers()


@pytest.fixture
def distributor_headers():
    return distributor_agent_headers()


@pytest.fixture
def finance_headers():
    return finance_administrator_headers()
