"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def workout_officer_headers():
    return TEST_USERS["workout_officer_headers"]


@pytest.fixture
def special_assets_manager_headers():
    return TEST_USERS["special_assets_manager_headers"]


@pytest.fixture
def credit_committee_headers():
    return TEST_USERS["credit_committee_headers"]


@pytest.fixture
def appraisal_desk_headers():
    return TEST_USERS["appraisal_desk_headers"]


@pytest.fixture
def legal_counsel_headers():
    return TEST_USERS["legal_counsel_headers"]


@pytest.fixture
def loan_accounting_headers():
    return TEST_USERS["loan_accounting_headers"]


@pytest.fixture
def portfolio_analyst_headers():
    return TEST_USERS["portfolio_analyst_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]
