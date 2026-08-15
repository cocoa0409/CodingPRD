"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def gala_admin_headers():
    return TEST_USERS["gala_admin_headers"]


@pytest.fixture
def procurement_officer_headers():
    return TEST_USERS["procurement_officer_headers"]


@pytest.fixture
def valuation_approver_headers():
    return TEST_USERS["valuation_approver_headers"]


@pytest.fixture
def catalog_manager_headers():
    return TEST_USERS["catalog_manager_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def bidder_headers():
    return TEST_USERS["bidder_headers"]


@pytest.fixture
def donor_headers():
    return TEST_USERS["donor_headers"]
