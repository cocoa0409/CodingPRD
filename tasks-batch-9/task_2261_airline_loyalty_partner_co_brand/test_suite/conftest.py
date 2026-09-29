"""Shared pytest fixtures for the airline loyalty co-brand economics suite.

The harness restarts the service before every individual test, so every test
starts against an empty database and builds its own preconditions through the
endpoints the PRD declares.  Nothing here creates domain rows.
"""
import pytest

from test_helpers import TEST_USERS, api_client


@pytest.fixture(scope="session")
def api():
    """The endpoint client, one method per path in the PRD's endpoint table."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def second_program_admin_headers():
    return TEST_USERS["second_program_admin_headers"]


@pytest.fixture
def partner_manager_headers():
    return TEST_USERS["partner_manager_headers"]


@pytest.fixture
def second_partner_manager_headers():
    return TEST_USERS["second_partner_manager_headers"]


@pytest.fixture
def contracts_officer_headers():
    return TEST_USERS["contracts_officer_headers"]


@pytest.fixture
def second_contracts_officer_headers():
    return TEST_USERS["second_contracts_officer_headers"]


@pytest.fixture
def revenue_accountant_headers():
    return TEST_USERS["revenue_accountant_headers"]


@pytest.fixture
def fraud_analyst_headers():
    return TEST_USERS["fraud_analyst_headers"]


@pytest.fixture
def second_fraud_analyst_headers():
    return TEST_USERS["second_fraud_analyst_headers"]


@pytest.fixture
def issuer_representative_headers():
    """Fallback IssuerRepresentative headers for calls that are not scope-gated.

    Scope-gated calls must instead build headers from the acting issuer's own row
    id, because ``X-User-ID`` is compared to the agreement's ``issuer_id``.
    """
    return TEST_USERS["issuer_representative_headers"]


@pytest.fixture
def member_headers():
    """Fallback Member headers for calls that are not scope-gated.

    Scope-gated calls must instead build headers from the acting member's own row
    id, because ``X-User-ID`` is compared to the resource's ``member_id``.
    """
    return TEST_USERS["member_headers"]
