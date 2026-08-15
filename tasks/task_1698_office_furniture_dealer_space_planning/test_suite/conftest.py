"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def dealer_admin_headers():
    return TEST_USERS["dealer_admin_headers"]


@pytest.fixture
def account_executive_headers():
    return TEST_USERS["account_executive_headers"]


@pytest.fixture
def contracts_officer_headers():
    return TEST_USERS["contracts_officer_headers"]


@pytest.fixture
def designer_headers():
    return TEST_USERS["designer_headers"]


@pytest.fixture
def client_approver_headers():
    return TEST_USERS["client_approver_headers"]


@pytest.fixture
def project_manager_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def warehouse_lead_headers():
    return TEST_USERS["warehouse_lead_headers"]


@pytest.fixture
def claims_coordinator_headers():
    return TEST_USERS["claims_coordinator_headers"]


@pytest.fixture
def manufacturer_rep_headers():
    return TEST_USERS["manufacturer_rep_headers"]


@pytest.fixture
def liquidation_appraiser_headers():
    return TEST_USERS["liquidation_appraiser_headers"]


@pytest.fixture
def finance_manager_headers():
    return TEST_USERS["finance_manager_headers"]
