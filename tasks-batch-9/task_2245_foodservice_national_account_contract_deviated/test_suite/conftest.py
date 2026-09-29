"""Shared pytest fixtures for the National Account Contract compliance suite."""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_contract_auditor_headers,
    make_national_account_manager_headers,
    make_pricing_analyst_headers,
    make_rebate_accountant_headers,
    make_system_admin_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The HTTP client for the service under test."""
    return api_client


@pytest.fixture
def admin_headers():
    """SystemAdmin: reference data and the logical clock."""
    return make_system_admin_headers()


@pytest.fixture
def manager_headers():
    """NationalAccountManager: contract construction, activation, invoicing."""
    return make_national_account_manager_headers()


@pytest.fixture
def analyst_headers():
    """PricingAnalyst: deviated pricing drafts and cost change notices."""
    return make_pricing_analyst_headers()


@pytest.fixture
def accountant_headers():
    """RebateAccountant: rebate periods and bill-back accrual and cash."""
    return make_rebate_accountant_headers()


@pytest.fixture
def auditor_headers():
    """ContractAuditor: dispute audits, credits, write-offs, reversals."""
    return make_contract_auditor_headers()


@pytest.fixture
def role_headers():
    """All five opaque-identity role header sets, keyed by role."""
    return TEST_USERS
