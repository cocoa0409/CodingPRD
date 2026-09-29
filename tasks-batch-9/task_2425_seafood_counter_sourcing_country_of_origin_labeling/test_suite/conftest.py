"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def chain_admin_headers():
    return TEST_USERS["chain_admin_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def cool_reviewer_headers():
    return TEST_USERS["cool_reviewer_headers"]


@pytest.fixture
def claim_reviewer_headers():
    return TEST_USERS["claim_reviewer_headers"]


@pytest.fixture
def simp_reviewer_headers():
    return TEST_USERS["simp_reviewer_headers"]


@pytest.fixture
def ledger_officer_headers():
    return TEST_USERS["ledger_officer_headers"]


@pytest.fixture
def cold_chain_officer_headers():
    return TEST_USERS["cold_chain_officer_headers"]


@pytest.fixture
def merchandising_lead_headers():
    return TEST_USERS["merchandising_lead_headers"]


@pytest.fixture
def seafood_manager_headers():
    return TEST_USERS["seafood_manager_headers"]


@pytest.fixture
def supplier_rep_headers():
    return TEST_USERS["supplier_rep_headers"]
